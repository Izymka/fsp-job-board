from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fspml.assessment import grade_policy as gp
from fspml.assessment import scenarios as scn
from fspml.assessment.cat import CatPlan
from fspml.assessment.engine import AssessmentEngine
from fspml.assessment.irt import information, prob
from fspml.catalog import get_catalog
from fspml.nlp.vacancy import parse_need
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import get_db, utcnow
from ...core.errors import AppError, not_found, responses
from ...core.security import require_role
from ..candidates.router import get_profile
from ..users.models import User
from . import service
from .models import Attempt, AttemptItem

router = APIRouter(prefix="/api/assessment", tags=["Тестирование"])
CandidateUser = require_role("candidate")
GRADES = Literal["intern", "junior", "middle", "senior", "lead"]


class ItemOut(BaseModel):
    position: int
    kind: str  # single | multi | order | number | text | scenario | probe
    stage: str = "knowledge"  # knowledge | scenario | probe
    task: str | None = None
    prompt: str
    code: str | None
    code_lang: str | None
    options: list[str] | None
    skill: str
    skill_title: str
    time_limit: int
    issued_at: datetime


class AttemptOut(BaseModel):
    id: str
    specialization: str
    grade: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    answered: int
    max_items: int
    min_items: int
    blueprint: dict[str, float]
    item: ItemOut | None
    result: dict | None
    has_scenario: bool = False  # для грейдов Middle+ после теста знаний будет практический кейс
    integrity: dict | None = None  # живое состояние: сколько уходов со страницы ещё допустимо


class EligibilityOption(BaseModel):
    grade: str
    allowed: bool
    kind: str
    reason: str | None
    available_at: datetime | None


class BlueprintModule(BaseModel):
    skill: str
    techs: list[str]


class BlueprintOut(BaseModel):
    """Персональный состав теста: ядро специализации + модули по заявленному стеку."""

    weights: dict[str, float]
    core: list[str]
    modules: list[BlueprintModule]
    untested: list[str] = Field(description="Заявленные технологии, по которым в тесте нет заданий")
    explanation: list[str]


class EligibilityOut(BaseModel):
    specialization: str | None
    claimed_grade: str | None
    confirmed_grade: str | None
    confirmed_at: datetime | None
    last_change_at: datetime | None
    in_progress: str | None
    options: list[EligibilityOption]
    rules: list[str]
    blueprint: BlueprintOut | None = None


class StartIn(BaseModel):
    grade: GRADES


class AnswerIn(BaseModel):
    position: int = Field(ge=0)
    value: Any = Field(
        description="Индекс варианта (single), список индексов (multi/order), число (number) или строка (text)"
    )
    time_ms: int | None = Field(default=None, ge=0)
    tab_switches: int = Field(
        default=0, ge=0, le=1000, description="Уходы со страницы (вкладка/окно) ≥ 1,5 с"
    )
    away_ms: int = Field(default=0, ge=0, le=86_400_000, description="Суммарно вне страницы за задание, мс")
    paste_attempts: int = Field(default=0, ge=0, le=1000)
    copy_attempts: int = Field(default=0, ge=0, le=1000)


def _item_out(db: Session, attempt: Attempt, engine: AssessmentEngine) -> ItemOut | None:
    it = service.current_item(db, attempt)
    if it is None or attempt.status != "in_progress":
        return None
    skill_title = get_catalog().assessment_skills.get(it.skill, {}).get("title", it.skill)
    limit = service.item_time_limit(engine, it)
    if it.kind == "scenario":
        inst = service.scenario_instance(attempt, it)
        return ItemOut(
            position=it.position,
            kind="scenario",
            stage="scenario",
            task=inst.task.strip(),
            prompt=inst.prompt,
            code=inst.code,
            code_lang=inst.scenario.code_lang,
            options=None,
            skill=it.skill,
            skill_title=skill_title,
            time_limit=limit,
            issued_at=it.issued_at,
        )
    if it.kind == "probe":
        inst = service.scenario_instance(attempt, it)
        probe = inst.probe((it.meta or {}).get("probe", 0))
        return ItemOut(
            position=it.position,
            kind="probe",
            stage="probe",
            task=None,
            prompt=f"Уточняющий вопрос по вашему решению кейса «{inst.scenario.title}»:\n\n{probe.text}",
            code=None,
            code_lang=None,
            options=None,
            skill=it.skill,
            skill_title=skill_title,
            time_limit=limit,
            issued_at=it.issued_at,
        )
    inst = engine.regenerate(str(attempt.id), it.position, it.family_id)
    return ItemOut(
        position=it.position,
        skill=it.skill,
        skill_title=skill_title,
        time_limit=limit,
        issued_at=it.issued_at,
        **inst.public(),
    )


def attempt_out(db: Session, attempt: Attempt) -> AttemptOut:
    engine = service.get_engine(db)
    answered = db.scalars(
        select(AttemptItem.id).where(
            AttemptItem.attempt_id == attempt.id,
            AttemptItem.answered_at.is_not(None),
            AttemptItem.kind == "item",
        )
    ).all()
    live = None
    if attempt.status == "in_progress":
        rep = service.integrity_report(db, attempt, engine)
        live = {"items_left": rep.items_left, "leaves_left": rep.leaves_left, "level": rep.level}
    return AttemptOut(
        id=str(attempt.id),
        specialization=attempt.specialization,
        grade=attempt.grade,
        kind=attempt.kind,
        status=attempt.status,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        answered=len(answered),
        max_items=engine.config.max_items,
        min_items=engine.config.min_items,
        blueprint=attempt.blueprint,
        item=_item_out(db, attempt, engine),
        result=attempt.result,
        has_scenario=scn.needs_scenario(attempt.grade)
        and scn.pick_scenario(attempt.specialization, attempt.grade, 0) is not None,
        integrity=live,
    )


def _own_attempt(db: Session, user: User, attempt_id: str) -> Attempt:
    try:
        a = db.get(Attempt, uuid.UUID(attempt_id))
    except ValueError:
        a = None
    if a is None or a.candidate_id != user.id:
        raise not_found("Попытка")
    return a


RULES = [
    "Тест адаптивный: следующее задание подбирается по вашим ответам, у каждого кандидата — свой набор и свои варианты заданий.",
    "Состав теста — ядро специализации (общее для всех в категории) и модули по технологиям, которые вы заявили в опросе. Технологии, которых нет в вашем стеке, в тест не попадают.",
    "Грейд по результату теста не понижается. Если заявленный уровень не подтверждён, можно сразу пройти тест на уровень ниже.",
    "Повторная попытка на тот же или более высокий уровень после неудачи — через 14 дней.",
    "Смена подтверждённого грейда — не чаще одного раза в 90 дней.",
    "Брошенная попытка засчитывается как неудачная.",
    "Для Middle, Senior и Lead после теста знаний — практический кейс (до 15–18 минут) и уточняющий вопрос по вашему решению (2 минуты). Кейс оценивается по рубрике и учитывается в решении о грейде.",
    "На каждое задание есть ограничение по времени. Копировать текст заданий и вставлять текст в ответы нельзя.",
    "Уход со страницы теста (другая вкладка или окно) дольше 2 секунд фиксируется. Уходы на трёх заданиях или суммарно больше минуты — попытка аннулируется и засчитывается как неудачная. Единичные уходы видит работодатель рядом с результатом.",
]


@router.get(
    "/eligibility",
    response_model=EligibilityOut,
    summary="Доступные попытки и правила смены грейда",
    responses=responses(401, 403),
)
def eligibility(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    service.expire_stale(db, p)
    db.flush()
    state = service.grade_state(db, p)
    now = utcnow()
    opts = [
        EligibilityOption(
            grade=e.grade, allowed=e.allowed, kind=e.kind, reason=e.reason, available_at=e.available_at
        )
        for e in gp.available_targets(state, now)
    ]
    inprog = db.scalar(
        select(Attempt.id).where(Attempt.candidate_id == p.user_id, Attempt.status == "in_progress")
    )
    db.commit()
    bp = None
    if p.specialization:
        tb = service.get_engine(db).blueprint_for(p.specialization, list(p.stack or []))
        bp = BlueprintOut(
            weights={k: round(v, 4) for k, v in tb.weights.items()},
            core=list(tb.core),
            modules=[BlueprintModule(skill=s, techs=list(t)) for s, t in tb.modules.items()],
            untested=list(tb.untested),
            explanation=tb.explanation(),
        )
    return EligibilityOut(
        specialization=p.specialization,
        claimed_grade=p.claimed_grade,
        confirmed_grade=p.confirmed_grade,
        confirmed_at=p.confirmed_at,
        last_change_at=p.last_grade_change_at,
        in_progress=str(inprog) if inprog else None,
        options=opts,
        rules=RULES,
        blueprint=bp,
    )


@router.post(
    "/attempts",
    response_model=AttemptOut,
    status_code=201,
    summary="Начать тест на грейд",
    responses=responses(401, 403, 409),
)
def start(body: StartIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    attempt = service.start_attempt(db, p, body.grade)
    db.commit()
    return attempt_out(db, attempt)


@router.get(
    "/attempts", response_model=list[AttemptOut], summary="История попыток", responses=responses(401, 403)
)
def history(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Attempt).where(Attempt.candidate_id == user.id).order_by(Attempt.started_at.desc())
    ).all()
    return [attempt_out(db, a) for a in rows]


@router.get(
    "/attempts/{attempt_id}",
    response_model=AttemptOut,
    summary="Состояние попытки и текущее задание",
    responses=responses(401, 403, 404),
)
def get_attempt(attempt_id: str, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    return attempt_out(db, _own_attempt(db, user, attempt_id))


@router.post(
    "/attempts/{attempt_id}/answer",
    response_model=AttemptOut,
    summary="Ответить на текущее задание",
    responses=responses(401, 403, 404, 409),
)
def post_answer(
    attempt_id: str, body: AnswerIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)
):
    a = _own_attempt(db, user, attempt_id)
    p = get_profile(db, user)
    service.answer(
        db,
        p,
        a,
        body.position,
        body.value,
        body.time_ms,
        body.tab_switches,
        away_ms=body.away_ms,
        paste_attempts=body.paste_attempts,
        copy_attempts=body.copy_attempts,
    )
    db.commit()
    return attempt_out(db, a)


@router.post(
    "/attempts/{attempt_id}/abandon",
    response_model=AttemptOut,
    summary="Прервать попытку (засчитывается как неудачная)",
    responses=responses(401, 403, 404, 409),
)
def post_abandon(attempt_id: str, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    a = _own_attempt(db, user, attempt_id)
    service.abandon(db, a)
    db.commit()
    return attempt_out(db, a)


# ------------------------------------------------------------------ тест из вакансии (демонстрация)


class PreviewIn(BaseModel):
    text: str | None = Field(default=None, max_length=20000)
    title: str | None = Field(default=None, max_length=255)
    vacancy_id: str | None = None
    grade: GRADES | None = None
    candidates: int = Field(default=2, ge=1, le=3)
    items: int = Field(default=8, ge=3, le=15)


class PreviewItem(BaseModel):
    family_id: str
    family_title: str
    skill: str
    skill_title: str
    level: int
    difficulty_b: float
    info_at_cut: float
    kind: str
    prompt: str
    code: str | None
    code_lang: str | None
    options: list[str] | None


class PreviewTest(BaseModel):
    label: str
    items: list[PreviewItem]
    mean_b: float
    total_information: float
    skill_mix: dict[str, int]


class PreviewOut(BaseModel):
    specialization: str | None
    grade: str
    blueprint: dict[str, float]
    parsed_skills: dict[str, float]
    explanation: list[str]
    tests: list[PreviewTest]
    shared_families: int
    shared_instances: int


@router.post(
    "/preview",
    response_model=PreviewOut,
    summary="Как система формирует тест по описанию вакансии",
    responses=responses(400, 404),
)
def preview(body: PreviewIn, db: Session = Depends(get_db)):
    """Разбор вакансии → blueprint → несколько независимых адаптивных прогонов для кандидатов
    одинаковой силы. Показывает, что тесты разные (утечка одного бесполезна для другого),
    но сопоставимы по составу навыков и сложности."""
    cat = get_catalog()
    if body.vacancy_id:
        from ..vacancies.models import Vacancy

        try:
            v = db.get(Vacancy, uuid.UUID(body.vacancy_id))
        except ValueError:
            v = None
        if v is None:
            raise not_found("Вакансия")
        text, title, grade = v.text, v.title, body.grade or v.grade
    else:
        if not body.text:
            raise AppError(400, "text_required", "Передайте текст вакансии или vacancy_id")
        text, title, grade = body.text, body.title or "", body.grade
    need = parse_need(text, title)
    grade = grade or need.grade or "middle"
    if not need.blueprint:
        raise AppError(400, "no_skills", "В тексте не найдено навыков, которые проверяет тест")
    engine = AssessmentEngine(get_settings().assessment_secret.encode())
    plan: CatPlan = engine.plan_for_blueprint(need.blueprint, grade)
    plan = CatPlan(
        plan.blueprint,
        grade,
        plan.config.__class__(**{**plan.config.__dict__, "max_items": body.items, "min_items": body.items}),
    )
    cut = cat.grade(grade).cut
    tests: list[PreviewTest] = []
    seen_f: list[set[str]] = []
    seen_i: list[set[str]] = []
    for k in range(body.candidates):
        attempt_id = f"preview-{uuid.uuid4()}"
        rng = random.Random(k)
        responses_ = []
        items: list[PreviewItem] = []
        while (issued := engine.next_item(attempt_id, plan, responses_)) is not None:
            f, inst = issued.family, issued.instance
            items.append(
                PreviewItem(
                    family_id=f.id,
                    family_title=f.title,
                    skill=f.skill,
                    skill_title=cat.assessment_skills.get(f.skill, {}).get("title", f.skill),
                    level=f.level,
                    difficulty_b=round(float(f.b), 2),
                    info_at_cut=round(float(information(cut, f.a, f.b, f.c)), 3),
                    **inst.public(),
                )
            )
            # симулируем кандидата ровно на пороге грейда
            responses_.append(engine.response(f.id, rng.random() < float(prob(cut, f.a, f.b, f.c))))
        mix: dict[str, int] = {}
        for it in items:
            mix[it.skill] = mix.get(it.skill, 0) + 1
        tests.append(
            PreviewTest(
                label=f"Кандидат {chr(65 + k)}",
                items=items,
                mean_b=round(sum(i.difficulty_b for i in items) / len(items), 2),
                total_information=round(sum(i.info_at_cut for i in items), 2),
                skill_mix=mix,
            )
        )
        seen_f.append({i.family_id for i in items})
        seen_i.append({i.prompt + (i.code or "") for i in items})
    shared_f = len(set.intersection(*seen_f)) if len(seen_f) > 1 else 0
    shared_i = len(set.intersection(*seen_i)) if len(seen_i) > 1 else 0
    return PreviewOut(
        specialization=need.specialization,
        grade=grade,
        blueprint=need.blueprint,
        parsed_skills=need.skills,
        explanation=need.explanation,
        tests=tests,
        shared_families=shared_f,
        shared_instances=shared_i,
    )
