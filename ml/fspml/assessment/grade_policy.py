"""Машина состояний грейда: когда можно пройти тест и как результат меняет грейд.

Правила (docs/PLAN.md §2):
* грейд никогда не понижается по результату теста; неудача лишь фиксируется;
* *онбординг* (подтверждённого грейда ещё нет): тест на любой грейд, после неудачи на грейд g
  тест на грейд ниже g доступен сразу, на g и выше — через `retry_days`;
* первое подтверждение не считается сменой грейда, поэтому сразу после него доступно
  повышение на одну ступень (если тест показал уверенный результат);
* после онбординга смена грейда (вверх на одну ступень или добровольно вниз) — не чаще чем
  раз в `change_days`; повторный тест на текущий грейд (обновить результат) — раз в `retry_days`;
* брошенная попытка приравнивается к неудачной — нельзя «перезапускать» тест до удачного набора;
* аннулированная попытка (систематические уходы со страницы теста, см. `integrity.py`) — тоже.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from ..catalog import Catalog, get_catalog

AttemptStatus = Literal["in_progress", "passed", "failed", "abandoned", "voided"]
FAILED_STATUSES = ("failed", "abandoned", "voided")
AttemptKind = Literal["initial", "upgrade", "downgrade", "refresh"]


@dataclass(frozen=True)
class PolicyConfig:
    change_days: int = 90
    retry_days: int = 14


@dataclass(frozen=True)
class AttemptRecord:
    grade: str
    status: AttemptStatus
    started_at: datetime
    finished_at: datetime | None = None


@dataclass(frozen=True)
class GradeState:
    confirmed_grade: str | None = None
    confirmed_at: datetime | None = None
    last_change_at: datetime | None = None
    attempts: tuple[AttemptRecord, ...] = ()


@dataclass(frozen=True)
class Eligibility:
    grade: str
    allowed: bool
    kind: AttemptKind
    reason: str | None = None
    available_at: datetime | None = None


def _kind(state: GradeState, target: str, catalog: Catalog) -> AttemptKind:
    if state.confirmed_grade is None:
        return "initial"
    t, c = catalog.grade_index(target), catalog.grade_index(state.confirmed_grade)
    if t > c:
        return "upgrade"
    if t < c:
        return "downgrade"
    return "refresh"


def check_attempt(
    state: GradeState,
    target: str,
    now: datetime,
    *,
    config: PolicyConfig = PolicyConfig(),
    catalog: Catalog | None = None,
) -> Eligibility:
    catalog = catalog or get_catalog()
    kind = _kind(state, target, catalog)
    t_idx = catalog.grade_index(target)

    if any(a.status == "in_progress" for a in state.attempts):
        return Eligibility(target, False, kind, "Завершите текущую попытку тестирования")

    blockers: list[tuple[datetime, str]] = []

    # Неудача на грейде g блокирует g и выше на retry_days.
    for a in state.attempts:
        if a.status in FAILED_STATUSES and a.finished_at and catalog.grade_index(a.grade) <= t_idx:
            until = a.finished_at + timedelta(days=config.retry_days)
            if until > now:
                blockers.append(
                    (
                        until,
                        f"Повторная попытка на этот уровень — через {config.retry_days} дней после неудачной",
                    )
                )

    if kind == "upgrade" and t_idx - catalog.grade_index(state.confirmed_grade) > 1:
        return Eligibility(target, False, kind, "Повышение возможно только на одну ступень за раз")

    if kind in ("upgrade", "downgrade") and state.last_change_at is not None:
        until = state.last_change_at + timedelta(days=config.change_days)
        if until > now:
            blockers.append((until, f"Грейд можно менять не чаще раза в {config.change_days} дней"))

    if kind == "refresh":
        last = max(
            (a.finished_at for a in state.attempts if a.grade == target and a.finished_at), default=None
        )
        if last is not None and last + timedelta(days=config.retry_days) > now:
            blockers.append(
                (
                    last + timedelta(days=config.retry_days),
                    f"Обновить результат можно через {config.retry_days} дней",
                )
            )

    if blockers:
        until, reason = max(blockers)
        return Eligibility(target, False, kind, reason, until)
    return Eligibility(target, True, kind)


def available_targets(
    state: GradeState, now: datetime, *, config: PolicyConfig = PolicyConfig(), catalog: Catalog | None = None
) -> list[Eligibility]:
    catalog = catalog or get_catalog()
    return [check_attempt(state, g.id, now, config=config, catalog=catalog) for g in catalog.grades]


def start_attempt(state: GradeState, target: str, now: datetime, **kw) -> GradeState:
    elig = check_attempt(state, target, now, **kw)
    if not elig.allowed:
        raise PermissionError(elig.reason)
    return replace(state, attempts=(*state.attempts, AttemptRecord(target, "in_progress", now)))


def finish_attempt(state: GradeState, passed: bool | None, now: datetime) -> tuple[GradeState, str | None]:
    """Завершить текущую попытку. passed=None — попытка брошена.

    Возвращает новое состояние и событие: "confirmed" (первое подтверждение), "changed",
    "refreshed" или None.
    """
    attempts = list(state.attempts)
    idx = next((i for i, a in enumerate(attempts) if a.status == "in_progress"), None)
    if idx is None:
        raise ValueError("нет активной попытки")
    current = attempts[idx]
    status: AttemptStatus = "abandoned" if passed is None else ("passed" if passed else "failed")
    attempts[idx] = replace(current, status=status, finished_at=now)
    new = replace(state, attempts=tuple(attempts))
    if not passed:
        return new, None
    if state.confirmed_grade is None:
        return replace(new, confirmed_grade=current.grade, confirmed_at=now), "confirmed"
    if current.grade != state.confirmed_grade:
        return replace(new, confirmed_grade=current.grade, confirmed_at=now, last_change_at=now), "changed"
    return replace(new, confirmed_at=now), "refreshed"


def history_from_records(records: Sequence[AttemptRecord], **kw) -> GradeState:
    """Восстановить состояние из журнала попыток (в порядке начала)."""
    state = GradeState(**kw)
    return replace(state, attempts=tuple(sorted(records, key=lambda a: a.started_at)))
