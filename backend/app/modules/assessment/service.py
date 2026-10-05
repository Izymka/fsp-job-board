"""Оркестрация тестирования: политика грейда + движок CAT + хранение попыток + мониторинг утечек."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

from fspml.assessment import grade_policy as gp
from fspml.assessment.cat import CatPlan, CatResult, Response, estimate
from fspml.assessment.drift import CusumConfig
from fspml.assessment.engine import AssessmentEngine, IssuedItem
from fspml.assessment.irt import ItemParams, prob
from fspml.catalog import get_catalog
from fspml.nlp.skills import get_dictionary
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import aware, utcnow
from ...core.errors import AppError
from ..candidates.models import CandidateProfile
from .models import Attempt, AttemptItem, FamilyStats

STALE_AFTER = timedelta(hours=3)
TIME_GRACE_SEC = 20

_engine_cache: tuple[float, AssessmentEngine] | None = None
_exposure_cache: tuple[float, dict[str, float]] | None = None


def get_engine(db: Session) -> AssessmentEngine:
    """Движок с актуальными параметрами семейств (перекалибровка, вывод из ротации). Кеш 60 с."""
    global _engine_cache
    now = time.time()
    if _engine_cache and now - _engine_cache[0] < 60:
        return _engine_cache[1]
    stats = db.scalars(select(FamilyStats)).all()
    params = {s.family_id: ItemParams(s.a, s.b) for s in stats if s.a is not None and s.b is not None}
    disabled = {s.family_id for s in stats if s.disabled}
    eng = AssessmentEngine(get_settings().assessment_secret.encode(), params=params, disabled=disabled)
    _engine_cache = (now, eng)
    return eng


def reset_engine_cache() -> None:
    global _engine_cache, _exposure_cache
    _engine_cache = None
    _exposure_cache = None


def exposure_rates(db: Session) -> dict[str, float]:
    """Доля попыток за 30 дней, в которых показывалось семейство (для контроля экспозиции)."""
    global _exposure_cache
    now = time.time()
    if _exposure_cache and now - _exposure_cache[0] < 300:
        return _exposure_cache[1]
    since = utcnow() - timedelta(days=30)
    n_attempts = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.started_at >= since)) or 0
    rates: dict[str, float] = {}
    if n_attempts >= 50:  # при малом числе попыток контроль экспозиции не имеет смысла
        rows = db.execute(
            select(AttemptItem.family_id, func.count(func.distinct(AttemptItem.attempt_id)))
            .join(Attempt, Attempt.id == AttemptItem.attempt_id)
            .where(Attempt.started_at >= since)
            .group_by(AttemptItem.family_id)
        ).all()
        rates = {fid: cnt / n_attempts for fid, cnt in rows}
    _exposure_cache = (now, rates)
    return rates


def stack_languages(stack: list[str]) -> list[str]:
    dic = get_dictionary()
    return sorted({a for t in stack or [] for a in (dic.techs[t].assess if t in dic.techs else ())})


def grade_state(db: Session, p: CandidateProfile) -> gp.GradeState:
    rows = db.scalars(
        select(Attempt)
        .where(Attempt.candidate_id == p.user_id, Attempt.specialization == p.specialization)
        .order_by(Attempt.started_at)
    ).all()
    return gp.GradeState(
        confirmed_grade=p.confirmed_grade,
        confirmed_at=aware(p.confirmed_at),
        last_change_at=aware(p.last_grade_change_at),
        attempts=tuple(
            gp.AttemptRecord(a.grade, a.status, aware(a.started_at), aware(a.finished_at)) for a in rows
        ),
    )


def expire_stale(db: Session, p: CandidateProfile) -> None:
    for a in db.scalars(
        select(Attempt).where(Attempt.candidate_id == p.user_id, Attempt.status == "in_progress")
    ).all():
        if utcnow() - aware(a.started_at) > STALE_AFTER:
            a.status = "abandoned"
            a.finished_at = utcnow()


def plan_for(attempt: Attempt, engine: AssessmentEngine) -> CatPlan:
    return CatPlan(
        blueprint=dict(attempt.blueprint),
        claimed_grade=attempt.grade,
        config=engine.config,
        kind=attempt.kind,
    )


def responses_of(db: Session, attempt: Attempt, engine: AssessmentEngine) -> list[Response]:
    items = db.scalars(
        select(AttemptItem)
        .where(AttemptItem.attempt_id == attempt.id, AttemptItem.answered_at.is_not(None))
        .order_by(AttemptItem.position)
    ).all()
    return [engine.response(it.family_id, bool(it.correct)) for it in items]


def current_item(db: Session, attempt: Attempt) -> AttemptItem | None:
    return db.scalar(
        select(AttemptItem)
        .where(AttemptItem.attempt_id == attempt.id, AttemptItem.answered_at.is_(None))
        .order_by(AttemptItem.position.desc())
    )


def issue_next(
    db: Session, attempt: Attempt, engine: AssessmentEngine, responses: list[Response]
) -> IssuedItem | None:
    plan = plan_for(attempt, engine)
    issued = engine.next_item(str(attempt.id), plan, responses, exposure=exposure_rates(db))
    if issued is None:
        return None
    post = estimate(responses, engine.config)
    f = issued.family
    expected = float(prob(post.mean, f.a, f.b, f.c))
    db.add(
        AttemptItem(
            attempt_id=attempt.id,
            position=issued.position,
            family_id=f.id,
            skill=f.skill,
            expected_p=expected,
        )
    )
    db.flush()
    return issued


def start_attempt(db: Session, p: CandidateProfile, grade: str) -> Attempt:
    if not p.survey_completed_at or not p.specialization:
        raise AppError(
            409, "survey_required", "Сначала пройдите опрос: специализация и стек определяют содержание теста"
        )
    expire_stale(db, p)
    db.flush()
    state = grade_state(db, p)
    now = utcnow()
    elig = gp.check_attempt(state, grade, now)
    if not elig.allowed:
        raise AppError(
            409,
            "attempt_not_allowed",
            elig.reason or "Попытка недоступна",
            {"available_at": elig.available_at.isoformat() if elig.available_at else None},
        )
    engine = get_engine(db)
    plan = engine.plan_for_specialization(p.specialization, grade, stack_languages(p.stack), kind=elig.kind)
    attempt = Attempt(
        id=uuid.uuid4(),
        candidate_id=p.user_id,
        specialization=p.specialization,
        grade=grade,
        kind=elig.kind,
        blueprint=plan.blueprint,
        stack=list(p.stack or []),
        started_at=now,
    )
    db.add(attempt)
    db.flush()
    issue_next(db, attempt, engine, [])
    p.last_active_at = now
    return attempt


def _update_family_stats(db: Session, item: AttemptItem, cfg: CusumConfig = CusumConfig()) -> None:
    st = db.get(FamilyStats, item.family_id)
    if st is None:
        st = FamilyStats(family_id=item.family_id, n_responses=0, n_correct=0, cusum=0.0)
        db.add(st)
    st.n_responses = (st.n_responses or 0) + 1
    st.n_correct = (st.n_correct or 0) + int(bool(item.correct))
    if item.expected_p is not None:
        st.cusum = max(0.0, (st.cusum or 0.0) + (float(bool(item.correct)) - item.expected_p) - cfg.k)
        if st.flagged_at is None and st.n_responses >= cfg.min_n and st.cusum > cfg.h:
            # семейство вероятно утекло: выводим из ротации до ревизии
            st.flagged_at = utcnow()
            st.disabled = True
            reset_engine_cache()


def answer(
    db: Session,
    p: CandidateProfile,
    attempt: Attempt,
    position: int,
    value,
    time_ms: int | None,
    tab_switches: int,
) -> CatResult | None:
    if attempt.status != "in_progress":
        raise AppError(409, "attempt_finished", "Попытка уже завершена")
    item = current_item(db, attempt)
    if item is None or item.position != position:
        raise AppError(409, "wrong_position", "Ответ на это задание уже принят или задание не выдано")
    engine = get_engine(db)
    inst = engine.regenerate(str(attempt.id), item.position, item.family_id)
    fam = engine.bank.get(item.family_id)
    limit = (fam.time_limit if fam else 180) + TIME_GRACE_SEC
    elapsed = (utcnow() - aware(item.issued_at)).total_seconds()
    timed_out = elapsed > limit
    item.correct = (not timed_out) and inst.check(value)
    item.response = {"value": value, "timed_out": timed_out}
    item.answered_at = utcnow()
    item.time_ms = time_ms if time_ms is not None else int(elapsed * 1000)
    item.tab_switches = max(0, int(tab_switches or 0))
    _update_family_stats(db, item)
    db.flush()
    responses = responses_of(db, attempt, engine)
    nxt = issue_next(db, attempt, engine, responses)
    p.last_active_at = utcnow()
    if nxt is not None:
        return None
    return finish(db, p, attempt, engine, responses)


def finish(
    db: Session, p: CandidateProfile, attempt: Attempt, engine: AssessmentEngine, responses: list[Response]
) -> CatResult:
    result = engine.finish(plan_for(attempt, engine), responses)
    now = utcnow()
    passed = result.decision == "confirmed"
    state = grade_state(db, p)
    new_state, event = gp.finish_attempt(state, passed, now)
    attempt.status = "passed" if passed else "failed"
    attempt.finished_at = now
    switches = (
        db.scalar(select(func.sum(AttemptItem.tab_switches)).where(AttemptItem.attempt_id == attempt.id)) or 0
    )
    attempt.result = result_payload(result, switches)
    if passed:
        p.confirmed_grade = new_state.confirmed_grade
        p.confirmed_at = now
        if event == "changed":
            p.last_grade_change_at = now
        p.theta, p.theta_se = result.theta, result.se
        p.skill_scores = {
            k: {"status": s.status, "theta": s.theta, "se": s.se, "n": s.n_items, "n_correct": s.n_correct}
            for k, s in result.skills.items()
        }
    return result


def abandon(db: Session, attempt: Attempt) -> None:
    if attempt.status != "in_progress":
        raise AppError(409, "attempt_finished", "Попытка уже завершена")
    attempt.status = "abandoned"
    attempt.finished_at = utcnow()


def result_payload(r: CatResult, tab_switches: int = 0) -> dict:
    cat = get_catalog()
    g = cat.grade(r.claimed_grade)
    lines = [
        f"Оценка способности θ = {r.theta:+.2f} ± {r.se:.2f} (шкала специализации, средний кандидат — 0).",
        f"Вероятность, что уровень выше порога {g.name}: {r.p_claimed:.0%}.",
    ]
    if r.decision == "confirmed":
        lines.append(f"Грейд {g.name} подтверждён.")
        if r.suggestion == "upgrade":
            nxt = cat.grade_by_index(g.order + 1)
            lines.append(f"Результат уверенный — можно сразу пройти тест на {nxt.name}.")
    else:
        lines.append(
            f"Грейд {g.name} пока не подтверждён. Грейд не понижается: можно пройти тест на уровень ниже сейчас или повторить этот через 14 дней."
        )
    return {
        "theta": r.theta,
        "se": r.se,
        "n_items": r.n_items,
        "claimed_grade": r.claimed_grade,
        "p_claimed": r.p_claimed,
        "p_next": r.p_next,
        "decision": r.decision,
        "suggestion": r.suggestion,
        "estimated_grade": r.estimated_grade,
        "skills": {
            k: {"status": s.status, "theta": s.theta, "se": s.se, "n": s.n_items, "n_correct": s.n_correct}
            for k, s in r.skills.items()
        },
        "explanation": lines,
        "tab_switches": int(tab_switches),
    }
