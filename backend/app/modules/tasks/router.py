"""Регулярные короткие задания от работодателей: поддерживают актуальность профиля."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fspml.assessment.bank import REGISTRY
from fspml.assessment.items import instance_seed
from fspml.catalog import get_catalog
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import get_db, utcnow
from ...core.errors import AppError, conflict, not_found, responses
from ...core.security import require_role
from ..candidates.models import CandidateProfile
from ..candidates.router import get_profile
from ..candidates.service import anonymous_alias
from ..employers.models import Company
from ..employers.router import get_company
from ..users.models import User
from .models import RegularTask, TaskAssignment

router = APIRouter(tags=["Регулярные задания"])
EmployerUser = require_role("employer")
CandidateUser = require_role("candidate")
GRADE_LEVEL = {"intern": 1, "junior": 2, "middle": 3, "senior": 4, "lead": 5}


class TaskIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    kind: Literal["auto", "open"]
    specialization: str
    skill: str | None = Field(default=None, description="для auto — навык из банка заданий")
    prompt: str | None = Field(default=None, max_length=5000, description="для open — формулировка задачи")
    rubric: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def _check(self):
        cat = get_catalog()
        if self.specialization not in cat.specializations:
            raise ValueError("неизвестная специализация")
        if self.kind == "auto" and (not self.skill or self.skill not in cat.assessment_skills):
            raise ValueError("для автопроверяемого задания укажите навык из справочника")
        if self.kind == "open" and not self.prompt:
            raise ValueError("для открытого задания укажите формулировку")
        return self


class TaskOut(BaseModel):
    id: str
    title: str
    kind: str
    specialization: str
    skill: str | None
    prompt: str | None
    rubric: str | None
    active: bool
    created_at: datetime
    assigned: int = 0
    submitted: int = 0


class AssignmentOut(BaseModel):
    id: str
    task_id: str
    title: str
    company_name: str
    kind: str
    status: str
    prompt: str
    code: str | None = None
    code_lang: str | None = None
    options: list[str] | None = None
    answer_kind: str
    assigned_at: datetime
    due_at: datetime | None
    submitted_at: datetime | None
    correct: bool | None
    score: float | None
    feedback: str | None
    candidate_alias: str | None = None
    answer: dict | None = None


class SubmitIn(BaseModel):
    value: Any = None
    text: str | None = Field(default=None, max_length=10000)


class ReviewIn(BaseModel):
    score: float = Field(ge=0, le=1)
    feedback: str | None = Field(default=None, max_length=3000)


def task_out(db: Session, t: RegularTask) -> TaskOut:
    counts = dict(
        db.execute(
            select(TaskAssignment.status, func.count())
            .where(TaskAssignment.task_id == t.id)
            .group_by(TaskAssignment.status)
        ).all()
    )
    return TaskOut(
        id=str(t.id),
        title=t.title,
        kind=t.kind,
        specialization=t.specialization,
        skill=t.skill,
        prompt=t.prompt,
        rubric=t.rubric,
        active=t.active,
        created_at=t.created_at,
        assigned=sum(counts.values()),
        submitted=counts.get("submitted", 0) + counts.get("reviewed", 0),
    )


def _instance(a: TaskAssignment):
    fam = REGISTRY.get(a.family_id or "")
    if fam is None:
        return None
    return fam.generate(instance_seed(get_settings().assessment_secret.encode(), f"task:{a.id}", 0))


def assignment_out(db: Session, a: TaskAssignment, *, employer: bool = False) -> AssignmentOut:
    t = db.get(RegularTask, a.task_id)
    c = db.get(Company, t.company_id) if t else None
    base = dict(
        id=str(a.id),
        task_id=str(a.task_id),
        title=t.title if t else "",
        company_name=c.name if c else "",
        kind=t.kind if t else "open",
        status=a.status,
        assigned_at=a.assigned_at,
        due_at=a.due_at,
        submitted_at=a.submitted_at,
        correct=a.correct,
        score=a.score,
        feedback=a.feedback,
    )
    if employer:
        p = db.get(CandidateProfile, a.candidate_id)
        base["candidate_alias"] = anonymous_alias(p) if p else None
        base["answer"] = a.answer
    if t and t.kind == "auto":
        inst = _instance(a)
        pub = inst.public() if inst else {"prompt": "Задание недоступно", "kind": "text"}
        return AssignmentOut(
            **base,
            prompt=pub["prompt"],
            code=pub.get("code"),
            code_lang=pub.get("code_lang"),
            options=pub.get("options"),
            answer_kind=pub["kind"],
        )
    return AssignmentOut(
        **base,
        prompt=(t.prompt if t else "") + (f"\n\n**Критерии оценки:** {t.rubric}" if t and t.rubric else ""),
        answer_kind="essay",
    )


# -------------------------------------------------------------------------------- работодатель


@router.post(
    "/api/employer/tasks",
    response_model=TaskOut,
    status_code=201,
    summary="Создать регулярное задание",
    responses=responses(401, 403, 409, 422),
)
def create_task(body: TaskIn, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    t = RegularTask(company_id=company.id, **body.model_dump())
    db.add(t)
    db.commit()
    return task_out(db, t)


@router.get(
    "/api/employer/tasks",
    response_model=list[TaskOut],
    summary="Мои задания",
    responses=responses(401, 403, 409),
)
def list_tasks(user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    return [
        task_out(db, t)
        for t in db.scalars(
            select(RegularTask)
            .where(RegularTask.company_id == company.id)
            .order_by(RegularTask.created_at.desc())
        ).all()
    ]


@router.get(
    "/api/employer/tasks/{task_id}/submissions",
    response_model=list[AssignmentOut],
    summary="Решения кандидатов",
    responses=responses(401, 403, 404, 409),
)
def submissions(task_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    try:
        t = db.get(RegularTask, uuid.UUID(task_id))
    except ValueError:
        t = None
    if t is None or t.company_id != company.id:
        raise not_found("Задание")
    rows = db.scalars(
        select(TaskAssignment)
        .where(TaskAssignment.task_id == t.id, TaskAssignment.status.in_(("submitted", "reviewed")))
        .order_by(TaskAssignment.submitted_at.desc())
    ).all()
    return [assignment_out(db, a, employer=True) for a in rows]


@router.post(
    "/api/employer/submissions/{assignment_id}/review",
    response_model=AssignmentOut,
    summary="Оценить решение по рубрике",
    responses=responses(401, 403, 404, 409),
)
def review(
    assignment_id: str, body: ReviewIn, user: User = Depends(EmployerUser), db: Session = Depends(get_db)
):
    company = get_company(db, user)
    try:
        a = db.get(TaskAssignment, uuid.UUID(assignment_id))
    except ValueError:
        a = None
    t = db.get(RegularTask, a.task_id) if a else None
    if a is None or t is None or t.company_id != company.id:
        raise not_found("Решение")
    if a.status not in ("submitted", "reviewed"):
        raise conflict("not_submitted", "Решение ещё не отправлено")
    a.score, a.feedback, a.status, a.reviewed_at = body.score, body.feedback, "reviewed", utcnow()
    p = db.get(CandidateProfile, a.candidate_id)
    if p:
        recompute_tasks_score(db, p)
    db.commit()
    return assignment_out(db, a, employer=True)


# ------------------------------------------------------------------------------------ кандидат


def recompute_tasks_score(db: Session, p: CandidateProfile) -> None:
    """Сила по регулярным заданиям с затуханием: свежие решения весят больше (полураспад 60 дней)."""
    now = utcnow()
    rows = db.scalars(
        select(TaskAssignment).where(
            TaskAssignment.candidate_id == p.user_id, TaskAssignment.status.in_(("submitted", "reviewed"))
        )
    ).all()
    total = 0.0
    for a in rows:
        s = a.score if a.score is not None else (1.0 if a.correct else 0.0 if a.correct is False else 0.5)
        age = (now - (a.submitted_at or a.assigned_at)).days
        total += s * 0.5 ** (age / 60)
    p.tasks_score = round(min(1.0, total / 3), 3)


def _maybe_assign(db: Session, p: CandidateProfile) -> None:
    if not p.confirmed_grade or not p.specialization:
        return
    interval = timedelta(days=get_settings().task_interval_days)
    last = db.scalar(
        select(func.max(TaskAssignment.assigned_at)).where(TaskAssignment.candidate_id == p.user_id)
    )
    if last and utcnow() - last < interval:
        return
    done = set(
        db.scalars(select(TaskAssignment.task_id).where(TaskAssignment.candidate_id == p.user_id)).all()
    )
    pool = [
        t
        for t in db.scalars(
            select(RegularTask).where(
                RegularTask.active.is_(True), RegularTask.specialization == p.specialization
            )
        ).all()
        if t.id not in done
    ]
    # приоритет — задания по навыкам, где подтверждение слабее (даём шанс подтвердить)
    weak = {k for k, v in (p.skill_scores or {}).items() if v.get("status") != "confirmed"}
    pool.sort(key=lambda t: (t.skill not in weak, random.random()))
    level = GRADE_LEVEL.get(p.confirmed_grade, 3)
    for t in pool:
        family_id = None
        if t.kind == "auto":
            fams = sorted(
                (f for f in REGISTRY.values() if f.skill == t.skill),
                key=lambda f: (abs(f.level - level), random.random()),
            )
            if not fams:
                continue  # по навыку нет заданий в банке — берём следующее задание
            family_id = fams[0].id
        db.add(
            TaskAssignment(
                id=uuid.uuid4(),
                task_id=t.id,
                candidate_id=p.user_id,
                family_id=family_id,
                due_at=utcnow() + timedelta(days=7),
            )
        )
        return


@router.get(
    "/api/candidate/tasks",
    response_model=list[AssignmentOut],
    summary="Мои регулярные задания (новое назначается раз в 2 недели)",
    responses=responses(401, 403),
)
def my_tasks(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    _maybe_assign(db, p)
    for a in db.scalars(
        select(TaskAssignment).where(
            TaskAssignment.candidate_id == p.user_id, TaskAssignment.status == "assigned"
        )
    ).all():
        if a.due_at and a.due_at < utcnow():
            a.status = "expired"
    db.commit()
    rows = db.scalars(
        select(TaskAssignment)
        .where(TaskAssignment.candidate_id == p.user_id)
        .order_by(TaskAssignment.assigned_at.desc())
    ).all()
    return [assignment_out(db, a) for a in rows]


@router.post(
    "/api/candidate/tasks/{assignment_id}/submit",
    response_model=AssignmentOut,
    summary="Отправить решение",
    responses=responses(400, 401, 403, 404, 409),
)
def submit(
    assignment_id: str, body: SubmitIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)
):
    p = get_profile(db, user)
    try:
        a = db.get(TaskAssignment, uuid.UUID(assignment_id))
    except ValueError:
        a = None
    if a is None or a.candidate_id != p.user_id:
        raise not_found("Задание")
    now = utcnow()
    if a.status == "assigned" and a.due_at and a.due_at < now:
        a.status = "expired"
        db.commit()
    if a.status != "assigned":
        raise conflict("not_open", "Задание уже отправлено или просрочено")
    t = db.get(RegularTask, a.task_id)
    if t.kind == "auto":
        inst = _instance(a)
        if inst is None:
            raise AppError(400, "task_unavailable", "Задание недоступно")
        a.correct = inst.check(body.value)
        a.answer = {"value": body.value}
        # подтверждение навыка регулярными заданиями: скользящее среднее
        ts = dict(p.task_skills or {})
        ts[t.skill] = round(0.7 * ts.get(t.skill, 0.5) + 0.3 * (1.0 if a.correct else 0.0), 3)
        p.task_skills = ts
    else:
        if not body.text:
            raise AppError(400, "text_required", "Опишите подход к решению")
        a.answer = {"text": body.text}
    a.status = "submitted"
    a.submitted_at = now
    p.last_active_at = now
    recompute_tasks_score(db, p)
    db.commit()
    return assignment_out(db, a)
