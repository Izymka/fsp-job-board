"""Оркестрация тестирования: политика грейда + движок CAT + хранение попыток + мониторинг утечек."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta

from fspml.assessment import grade_policy as gp
from fspml.assessment import integrity as integ
from fspml.assessment import scenarios as scn
from fspml.assessment.cat import CatPlan, CatResult, Response, estimate
from fspml.assessment.drift import CusumConfig
from fspml.assessment.engine import AssessmentEngine, IssuedItem
from fspml.assessment.irt import ItemParams, prob
from fspml.assessment.items import instance_seed
from fspml.assessment.scenario_grader import grade_answer, grade_probe
from fspml.catalog import get_catalog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import aware, utcnow
from ...core.errors import AppError
from ..candidates.models import CandidateProfile
from . import proctoring
from .models import Attempt, AttemptItem, FamilyStats

STALE_AFTER = timedelta(hours=3)
# Окно памяти о показанных заданиях: повторная попытка (не раньше чем через 14 дней) идёт на других
# семействах; через полгода банк успевает обновиться, и ограничение снимается.
SEEN_WINDOW = timedelta(days=180)
# Время на задание — ориентир, а не обрыв: ответ после него принимается и оценивается по существу,
# задание помечается «с превышением времени» (лимиты пока не откалиброваны по реальным ответам).
# Запас покрывает сеть и задержку отрисовки.
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
        seen=frozenset(attempt.seen_families or ()),
    )


def seen_families(db: Session, p: CandidateProfile, now: datetime) -> list[str]:
    """Семейства заданий из прошлых попыток кандидата по специализации за SEEN_WINDOW."""
    rows = db.scalars(
        select(AttemptItem.family_id)
        .join(Attempt, Attempt.id == AttemptItem.attempt_id)
        .where(
            Attempt.candidate_id == p.user_id,
            Attempt.specialization == p.specialization,
            Attempt.started_at >= now - SEEN_WINDOW,
            AttemptItem.kind == "item",
        )
        .distinct()
    ).all()
    return sorted(f for f in rows if f)


def responses_of(db: Session, attempt: Attempt, engine: AssessmentEngine) -> list[Response]:
    items = db.scalars(
        select(AttemptItem)
        .where(
            AttemptItem.attempt_id == attempt.id,
            AttemptItem.answered_at.is_not(None),
            AttemptItem.kind == "item",
        )
        .order_by(AttemptItem.position)
    ).all()
    return [engine.response(it.family_id, bool(it.correct)) for it in items]


def answered_items(db: Session, attempt: Attempt) -> list[AttemptItem]:
    return list(
        db.scalars(
            select(AttemptItem)
            .where(AttemptItem.attempt_id == attempt.id, AttemptItem.answered_at.is_not(None))
            .order_by(AttemptItem.position)
        ).all()
    )


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


def start_attempt(
    db: Session,
    p: CandidateProfile,
    grade: str,
    proctor: proctoring.ProctorStart | None = None,
    env: dict | None = None,
) -> Attempt:
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
    plan = engine.plan_for_specialization(
        p.specialization, grade, list(p.stack or []), kind=elig.kind, directions=list(p.directions or [])
    )
    attempt = Attempt(
        id=uuid.uuid4(),
        candidate_id=p.user_id,
        specialization=p.specialization,
        grade=grade,
        kind=elig.kind,
        blueprint=plan.blueprint,
        stack=list(p.stack or []),
        seen_families=seen_families(db, p, now),
        env=client_env(env),
        started_at=now,
    )
    db.add(attempt)
    db.flush()
    if proctor is not None:
        proctoring.start(db, attempt, proctor)
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


def _signals(it: AttemptItem) -> integ.ItemSignals:
    c = it.client or {}
    return integ.ItemSignals(
        it.tab_switches or 0,
        it.away_ms or 0,
        it.paste_attempts or 0,
        it.copy_attempts or 0,
        fullscreen_off_ms=int(c.get("fullscreen_off_ms") or 0),
        shrunk_ms=int(c.get("shrunk_ms") or 0),
        extended_screen=bool(c.get("extended_screen")),
        fullscreen_unavailable=bool(c.get("fullscreen_unavailable")),
    )


def _env(attempt: Attempt) -> integ.EnvSignals | None:
    e = attempt.env
    if not e:
        return None
    return integ.EnvSignals(
        virtual=e.get("virtual"),
        renderer=e.get("renderer"),
        webdriver=bool(e.get("webdriver")),
        extended_screen=bool(e.get("extended_screen")),
    )


def client_env(raw: dict | None) -> dict | None:
    """Окружение со старта попытки; тип видеоадаптера определяет сервер, а не клиент."""
    if not raw:
        return None
    renderer = (raw.get("renderer") or "")[:256] or None
    return {**raw, "renderer": renderer, "virtual": integ.classify_renderer(renderer)}


def _proctor_signals(it: AttemptItem) -> integ.ProctorSignals:
    d = it.proctor or {}
    return integ.ProctorSignals(
        **{k: int(d.get(k) or 0) for k in (*proctoring.SIGNAL_FIELDS, "mismatch", "uncertain", "checks")}
    )


def integrity_report(db: Session, attempt: Attempt, engine: AssessmentEngine) -> integ.IntegrityReport:
    items = answered_items(db, attempt)
    resp = responses_of(db, attempt, engine)
    theta = estimate(resp, engine.config).mean if resp else None
    return integ.assess(
        [_signals(it) for it in items],
        pairs=[(r.params, r.correct) for r in resp],
        theta=theta,
        proctor=[_proctor_signals(it) for it in items] if attempt.proctored else None,
        identity=(attempt.identity or {}).get("status") if attempt.proctored else None,
        env=_env(attempt),
    )


def scenario_item(db: Session, attempt: Attempt, kind: str = "scenario") -> AttemptItem | None:
    return db.scalar(
        select(AttemptItem).where(AttemptItem.attempt_id == attempt.id, AttemptItem.kind == kind)
    )


def scenario_instance(attempt: Attempt, item: AttemptItem) -> scn.ScenarioInstance:
    """Экземпляр кейса восстанавливается по seed позиции основного задания кейса."""
    meta = item.meta or {}
    sc = scn.load_scenarios()[meta["scenario"]]
    pos = meta.get("main_position", item.position)
    seed = instance_seed(get_settings().assessment_secret.encode(), str(attempt.id), pos)
    return sc.instance(seed, meta.get("skin"))


def _issue_scenario(db: Session, attempt: Attempt, position: int) -> AttemptItem | None:
    seed = instance_seed(get_settings().assessment_secret.encode(), str(attempt.id), position)
    seen_items = [
        it.meta or {}
        for it in db.scalars(
            select(AttemptItem)
            .join(Attempt, Attempt.id == AttemptItem.attempt_id)
            .where(Attempt.candidate_id == attempt.candidate_id, AttemptItem.kind == "scenario")
        ).all()
    ]
    seen = {m.get("scenario") for m in seen_items}
    sc = scn.pick_scenario(attempt.specialization, attempt.grade, seed, exclude={x for x in seen if x})
    if sc is None:
        return None
    # сюжет — по направлению и отраслям кандидата; уже виденные версии кейса — в последнюю очередь
    p = db.get(CandidateProfile, attempt.candidate_id)
    skin = scn.pick_skin(
        sc,
        seed,
        industries=list(p.industries or []) if p else [],
        directions=list(p.directions or []) if p else [],
        seen={m.get("skin") for m in seen_items if m.get("scenario") == sc.id},
    )
    it = AttemptItem(
        attempt_id=attempt.id,
        position=position,
        kind="scenario",
        family_id=f"scn:{sc.id}",
        skill=sc.skill,
        meta={"scenario": sc.id, "main_position": position, "skin": skin},
    )
    db.add(it)
    db.flush()
    return it


def item_time_limit(engine: AssessmentEngine, item: AttemptItem) -> int:
    if item.kind == "scenario":
        sc = scn.load_scenarios().get((item.meta or {}).get("scenario", ""))
        return sc.time_limit if sc else 900
    if item.kind == "probe":
        return scn.PROBE_TIME_LIMIT
    fam = engine.bank.get(item.family_id)
    return fam.time_limit if fam else 180


def answer(
    db: Session,
    p: CandidateProfile,
    attempt: Attempt,
    position: int,
    value,
    time_ms: int | None,
    tab_switches: int,
    *,
    away_ms: int = 0,
    paste_attempts: int = 0,
    copy_attempts: int = 0,
    proctor: dict | None = None,
    embedding: list[float] | None = None,
    client: dict | None = None,
) -> CatResult | None:
    if attempt.status != "in_progress":
        raise AppError(409, "attempt_finished", "Попытка уже завершена")
    item = current_item(db, attempt)
    if item is None or item.position != position:
        raise AppError(409, "wrong_position", "Ответ на это задание уже принят или задание не выдано")
    engine = get_engine(db)
    limit = item_time_limit(engine, item)
    elapsed = (utcnow() - aware(item.issued_at)).total_seconds()
    over = elapsed > limit + TIME_GRACE_SEC
    pace = {"overtime": over, "overtime_sec": int(elapsed - limit) if over else 0}
    item.answered_at = utcnow()
    item.time_ms = time_ms if time_ms is not None else int(elapsed * 1000)
    item.tab_switches = max(0, int(tab_switches or 0))
    item.away_ms = max(0, int(away_ms or 0))
    item.paste_attempts = max(0, int(paste_attempts or 0))
    item.copy_attempts = max(0, int(copy_attempts or 0))
    item.proctor = proctoring.item_signals(db, attempt, proctor, embedding)
    item.client = client
    p.last_active_at = utcnow()

    if item.kind == "item":
        inst = engine.regenerate(str(attempt.id), item.position, item.family_id)
        item.correct = inst.check(value)
        item.response = {"value": value, **pace}
        _update_family_stats(db, item)
    else:
        text = "" if value is None else str(value)[:8000]
        item.response = {"value": text, **pace}
        inst_s = scenario_instance(attempt, item)
        if item.kind == "scenario":
            g = grade_answer(inst_s, text)
            probe_idx = scn.choose_probe(inst_s, g.scores)
            item.score = scn.total_score(inst_s, g.scores, None)
            item.meta = {**(item.meta or {}), "grading": g.to_dict(), "probe": probe_idx}
        else:
            main = scenario_item(db, attempt)
            probe = inst_s.probe((item.meta or {}).get("probe", 0))
            g = grade_probe(inst_s, probe, ((main.response or {}).get("value") if main else "") or "", text)
            item.score = g.scores.get("probe", 0) / 3
            item.meta = {**(item.meta or {}), "grading": g.to_dict()}
    db.flush()

    # Надёжность: систематические уходы со страницы (и грубые нарушения при прокторе) аннулируют попытку сразу
    report = integrity_report(db, attempt, engine)
    if report.level == "void":
        void(db, attempt, report)
        return None

    responses = responses_of(db, attempt, engine)
    if item.kind == "item":
        nxt = issue_next(db, attempt, engine, responses)
        if nxt is not None:
            return None
        if scn.needs_scenario(attempt.grade) and scenario_item(db, attempt) is None:
            if _issue_scenario(db, attempt, position + 1) is not None:
                return None
    elif item.kind == "scenario":
        db.add(
            AttemptItem(
                attempt_id=attempt.id,
                position=position + 1,
                kind="probe",
                family_id=item.family_id,
                skill=item.skill,
                meta={
                    "scenario": (item.meta or {})["scenario"],
                    "skin": (item.meta or {}).get("skin"),
                    "main_position": item.position,
                    "probe": (item.meta or {}).get("probe", 0),
                },
            )
        )
        db.flush()
        return None
    return finish(db, p, attempt, engine, responses, report)


def pace_summary(db: Session, attempt: Attempt) -> dict:
    """Сколько заданий решено с превышением рекомендуемого времени (на оценку не влияет)."""
    items = answered_items(db, attempt)
    over = [it for it in items if (it.response or {}).get("overtime")]
    return {
        "items": len(items),
        "overtime_items": len(over),
        "overtime_sec": sum(int((it.response or {}).get("overtime_sec") or 0) for it in over),
    }


def scenario_outcome(db: Session, attempt: Attempt) -> dict | None:
    main = scenario_item(db, attempt)
    if main is None or main.answered_at is None:
        return None
    probe = scenario_item(db, attempt, "probe")
    inst = scenario_instance(attempt, main)
    g = (main.meta or {}).get("grading") or {}
    scores = {k: int(v) for k, v in (g.get("scores") or {}).items()}
    pg = ((probe.meta or {}).get("grading") or {}) if probe is not None and probe.answered_at else {}
    probe_score = (pg.get("scores") or {}).get("probe") if pg else None
    total = scn.total_score(inst, scores, probe_score)
    k = scn.category(total)
    probe_q = inst.probe((main.meta or {}).get("probe", 0)) if probe is not None else None
    return {
        "scenario_id": inst.scenario.id,
        "title": inst.title,
        "grade": inst.scenario.grade,
        "category": k,
        "category_title": scn.CATEGORY_TITLES[k],
        "total": round(total, 3),
        "method": g.get("method", "keywords"),
        "comment": g.get("comment"),
        "criteria": [
            {
                "id": c.id,
                "title": c.title,
                "score": scores.get(c.id, 0),
                "evidence": (g.get("evidence") or {}).get(c.id, ""),
            }
            for c in inst.criteria
        ],
        "probe": (
            {
                "question": probe_q.text,
                "score": probe_score,
                "evidence": (pg.get("evidence") or {}).get("probe", ""),
            }
            if probe_q is not None
            else None
        ),
    }


def finish(
    db: Session,
    p: CandidateProfile,
    attempt: Attempt,
    engine: AssessmentEngine,
    responses: list[Response],
    report: integ.IntegrityReport | None = None,
) -> CatResult:
    plan = plan_for(attempt, engine)
    knowledge = engine.finish(plan, responses)
    sc_out = scenario_outcome(db, attempt)
    extra = (
        scn.grm_loglik([(scn.grm_params(sc_out["grade"]), sc_out["category"])])
        if sc_out is not None
        else None
    )
    result = engine.finish(plan, responses, extra_loglik=extra) if extra is not None else knowledge
    report = report or integrity_report(db, attempt, engine)
    now = utcnow()
    passed = result.decision == "confirmed"
    state = grade_state(db, p)
    new_state, event = gp.finish_attempt(state, passed, now)
    attempt.status = "passed" if passed else "failed"
    attempt.finished_at = now
    pace = pace_summary(db, attempt)
    attempt.result = result_payload(result, report, knowledge=knowledge, scenario=sc_out, pace=pace)
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
        p.assessment_summary = {
            "attempt_id": str(attempt.id),
            "integrity": {"level": report.level, "severity": report.severity, "reasons": report.reasons},
            "proctoring": proctoring.summary(attempt, report),
            "pace": pace,
            "scenario": (
                {k: sc_out[k] for k in ("title", "category", "category_title", "method")} if sc_out else None
            ),
        }
    return result


def void(db: Session, attempt: Attempt, report: integ.IntegrityReport) -> None:
    attempt.status = "voided"
    attempt.finished_at = utcnow()
    attempt.result = {
        "decision": "voided",
        "integrity": report.to_dict(),
        "explanation": [
            "Попытка аннулирована: нарушены правила прохождения (" + "; ".join(report.reasons) + ").",
            "Аннулированная попытка засчитывается как неудачная: повторить тест на этот уровень можно "
            "через 14 дней, на уровень ниже — сразу.",
        ],
    }


def abandon(db: Session, attempt: Attempt) -> None:
    if attempt.status != "in_progress":
        raise AppError(409, "attempt_finished", "Попытка уже завершена")
    attempt.status = "abandoned"
    attempt.finished_at = utcnow()


def result_payload(
    r: CatResult,
    report: integ.IntegrityReport | None = None,
    *,
    knowledge: CatResult | None = None,
    scenario: dict | None = None,
    pace: dict | None = None,
) -> dict:
    cat = get_catalog()
    g = cat.grade(r.claimed_grade)
    lines = [
        f"Оценка способности θ = {r.theta:+.2f} ± {r.se:.2f} (шкала специализации, средний кандидат — 0).",
    ]
    if scenario is not None and knowledge is not None:
        lines.append(
            f"Тест знаний: P(уровень выше порога {g.name}) = {knowledge.p_claimed:.0%}; "
            f"практический кейс «{scenario['title']}» — {scenario['category_title']}."
        )
        lines.append(f"С учётом кейса вероятность, что уровень выше порога {g.name}: {r.p_claimed:.0%}.")
    else:
        lines.append(f"Вероятность, что уровень выше порога {g.name}: {r.p_claimed:.0%}.")
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
        "knowledge_p_claimed": knowledge.p_claimed if knowledge is not None else r.p_claimed,
        "scenario": scenario,
        "integrity": report.to_dict() if report is not None else None,
        "tab_switches": report.items_left if report is not None else 0,
        "pace": pace,
    }
