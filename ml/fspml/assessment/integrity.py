"""Надёжность прохождения теста: поведенческие сигналы браузера + статистика согласованности ответов.

Почему не «запрет и всё». Клиентские запреты (копирование, вставка) останавливают только
ленивое списывание: задание можно сфотографировать, а оверлей-подсказчик браузер не видит.
Поэтому решение принимается по **совокупности** признаков (как в Duolingo English Test:
поведенческие сигналы + статистика ответов + правило, понятное кандидату заранее):

* **Уход со страницы** — переключение вкладки или окна (`visibilitychange` + `blur`) с длительностью.
  Короткие (< `min_away_ms`) не считаются: случайный клик мимо окна не повод для подозрений.
* **Попытки копирования/вставки** — текст задания копировать нельзя, вставлять в ответ — тоже;
  сама попытка — сигнал.
* **Согласованность ответов (person-fit)** — стандартизованный индекс lz (Drasgow, Levine &
  Williams, 1985): насколько вероятна наблюдаемая последовательность верных/неверных ответов при
  оценённой способности θ. Сильно отрицательный lz — «неестественный» паттерн (верно на трудных,
  неверно на лёгких), типичный для частичной подсказки. Это мягкий сигнал: он не аннулирует
  результат сам по себе, а помечает его для работодателя.

Правило (известно кандидату до начала и показывается при каждом уходе):
* `void` — попытка аннулируется и засчитывается как неудачная, если уходов со страницы на
  разных заданиях ≥ `void_items`, или суммарно вне страницы ≥ `void_away_ms`, или попыток
  вставки ≥ `void_pastes`;
* `review` — результат засчитывается, но работодатель видит пометку, если были единичные уходы,
  попытки копирования/вставки или lz < `lz_threshold`;
* `clean` — замечаний нет.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal

from .irt import ItemParams, prob


@dataclass(frozen=True)
class IntegrityConfig:
    min_away_ms: int = 2000  # уход короче — не сигнал
    void_items: int = 3  # уходы на стольких разных заданиях → аннулирование
    void_away_ms: int = 60_000  # суммарно вне страницы
    void_pastes: int = 3
    lz_threshold: float = -2.0  # одностороннее p ≈ 0.023
    lz_min_items: int = 10


DEFAULT_INTEGRITY = IntegrityConfig()


@dataclass(frozen=True)
class ItemSignals:
    focus_losses: int = 0
    away_ms: int = 0
    paste_attempts: int = 0
    copy_attempts: int = 0


@dataclass
class IntegrityReport:
    level: Literal["clean", "review", "void"]
    items_left: int  # задания, во время которых кандидат уходил со страницы
    away_ms: int
    paste_attempts: int
    copy_attempts: int
    lz: float | None
    reasons: list[str] = field(default_factory=list)
    # сколько ещё уходов допустимо до аннулирования (для живого предупреждения)
    leaves_left: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def person_fit_lz(pairs: Sequence[tuple[ItemParams, bool]], theta: float) -> float | None:
    """Стандартизованный индекс lz для дихотомических ответов при способности θ."""
    if not pairs:
        return None
    l0 = e = v = 0.0
    for params, correct in pairs:
        p = float(min(max(prob(theta, params.a, params.b, params.c), 1e-6), 1 - 1e-6))
        q = 1.0 - p
        l0 += math.log(p) if correct else math.log(q)
        e += p * math.log(p) + q * math.log(q)
        v += p * q * math.log(p / q) ** 2
    if v <= 1e-9:
        return None
    return (l0 - e) / math.sqrt(v)


def _minutes(ms: int) -> str:
    s = round(ms / 1000)
    return f"{s // 60} мин {s % 60} с" if s >= 60 else f"{s} с"


def assess(
    signals: Sequence[ItemSignals],
    *,
    pairs: Sequence[tuple[ItemParams, bool]] = (),
    theta: float | None = None,
    config: IntegrityConfig = DEFAULT_INTEGRITY,
) -> IntegrityReport:
    left = [s for s in signals if s.focus_losses > 0 and s.away_ms >= config.min_away_ms]
    away = sum(s.away_ms for s in left)
    pastes = sum(s.paste_attempts for s in signals)
    copies = sum(s.copy_attempts for s in signals)
    lz = person_fit_lz(pairs, theta) if theta is not None and len(pairs) >= config.lz_min_items else None
    reasons: list[str] = []
    if left:
        reasons.append(f"уходы со страницы теста: {len(left)} задан., суммарно {_minutes(away)}")
    if pastes:
        reasons.append(f"попытки вставить текст в ответ: {pastes}")
    if copies:
        reasons.append(f"попытки скопировать текст задания: {copies}")
    void = len(left) >= config.void_items or away >= config.void_away_ms or pastes >= config.void_pastes
    if lz is not None and lz < config.lz_threshold:
        reasons.append(
            f"непоследовательный паттерн ответов (индекс согласованности lz = {lz:+.1f}): "
            "верные ответы на трудных заданиях при ошибках на лёгких"
        )
    level: Literal["clean", "review", "void"] = "void" if void else ("review" if reasons else "clean")
    return IntegrityReport(
        level=level,
        items_left=len(left),
        away_ms=away,
        paste_attempts=pastes,
        copy_attempts=copies,
        lz=None if lz is None else round(lz, 2),
        reasons=reasons,
        leaves_left=max(0, config.void_items - len(left)),
    )
