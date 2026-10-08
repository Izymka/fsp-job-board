from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fspml.catalog import get_catalog
from fspml.matching.scoring import Need, score_candidate
from fspml.nlp.vacancy import parse_need
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...core.errors import AppError, conflict, not_found, responses
from ...core.security import require_role
from ..candidates.models import CandidateProfile
from ..candidates.router import get_profile
from ..candidates.service import category_label, features
from ..employers.models import Company
from ..employers.router import get_company
from ..employers.service import CandidateCard, card
from ..invitations.router import company_stats
from ..users.models import User
from .models import Application, Vacancy

router = APIRouter(tags=["Вакансии и отклики"])
EmployerUser = require_role("employer")
CandidateUser = require_role("candidate")
GRADES = Literal["intern", "junior", "middle", "senior", "lead"]


def vacancy_need(v: Vacancy) -> Need:
    return Need(
        v.specialization,
        v.grade,
        v.skills or {},
        v.salary_from,
        v.salary_to,
        v.work_format,
        min_years=v.min_years,
    )


class VacancyIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    text: str = Field(min_length=20, max_length=20000)
    specialization: str | None = None
    grade: GRADES | None = None
    salary_from: int = Field(gt=0, le=10_000_000, description="Вилка «от», ₽ — обязательно")
    salary_to: int = Field(gt=0, le=10_000_000, description="Вилка «до», ₽ — обязательно")
    work_format: Literal["office", "hybrid", "remote"] | None = None
    city: str | None = Field(default=None, max_length=128)
    min_years: float | None = Field(
        default=None, ge=0, le=20, description="требуемый опыт, лет; если не задано — из текста"
    )
    status: Literal["draft", "published", "closed"] = "published"

    @model_validator(mode="after")
    def _salary(self):
        if self.salary_to < self.salary_from:
            raise ValueError("верхняя граница вилки меньше нижней")
        return self


class VacancyOut(BaseModel):
    id: str
    company_id: str
    company_name: str
    company_industry: str | None
    company_stats: dict | None = None
    title: str
    text: str
    specialization: str
    grade: str
    category: str
    skills: dict[str, float]
    salary_from: int
    salary_to: int
    work_format: str | None
    city: str | None
    min_years: float | None = None
    status: str
    blueprint: dict[str, float]
    created_at: datetime
    updated_at: datetime
    applications: int | None = None
    match: dict | None = None
    applied: bool | None = None


def vac_out(
    db: Session,
    v: Vacancy,
    *,
    employer_view: bool = False,
    match: dict | None = None,
    applied: bool | None = None,
) -> VacancyOut:
    cat = get_catalog()
    c = db.get(Company, v.company_id)
    n_apps = (
        db.scalar(select(func.count()).select_from(Application).where(Application.vacancy_id == v.id))
        if employer_view
        else None
    )
    return VacancyOut(
        id=str(v.id),
        company_id=str(v.company_id),
        company_name=c.name if c else "",
        company_industry=c.industry if c else None,
        company_stats=None if employer_view else company_stats(db, v.company_id),
        title=v.title,
        text=v.text,
        specialization=v.specialization,
        grade=v.grade,
        category=f"{cat.specializations[v.specialization].name} · {cat.grade(v.grade).name}",
        skills=v.skills or {},
        salary_from=v.salary_from,
        salary_to=v.salary_to,
        work_format=v.work_format,
        city=v.city,
        min_years=v.min_years,
        status=v.status,
        blueprint=v.blueprint or {},
        created_at=v.created_at,
        updated_at=v.updated_at,
        applications=n_apps,
        match=match,
        applied=applied,
    )


def _apply_body(v: Vacancy, body: VacancyIn) -> None:
    n = parse_need(body.text, body.title)
    spec = body.specialization or n.specialization
    grade = body.grade or n.grade
    if not spec or spec not in get_catalog().specializations:
        raise AppError(
            400, "specialization_required", "Не удалось определить специализацию — укажите её явно"
        )
    if not grade:
        raise AppError(400, "grade_required", "Не удалось определить грейд — укажите его явно")
    v.title, v.text = body.title, body.text
    v.specialization, v.grade = spec, grade
    v.skills = n.skills
    v.salary_from, v.salary_to = body.salary_from, body.salary_to
    v.work_format = body.work_format or n.work_format
    v.city = body.city
    v.min_years = body.min_years if body.min_years is not None else n.min_years
    v.status = body.status
    v.blueprint = n.blueprint
    v.parsed = {"must": n.must, "plus": n.plus, "explanation": n.explanation, "spec_scores": n.spec_scores}


def _own_vacancy(db: Session, company: Company, vacancy_id: str) -> Vacancy:
    try:
        v = db.get(Vacancy, uuid.UUID(vacancy_id))
    except ValueError:
        v = None
    if v is None or v.company_id != company.id:
        raise not_found("Вакансия")
    return v


@router.post(
    "/api/employer/vacancies",
    response_model=VacancyOut,
    status_code=201,
    summary="Опубликовать вакансию (вилка обязательна)",
    responses=responses(400, 401, 403, 409, 422),
)
def create_vacancy(body: VacancyIn, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    v = Vacancy(
        company_id=company.id,
        title=body.title,
        text=body.text,
        specialization="backend",
        grade="middle",
        salary_from=body.salary_from,
        salary_to=body.salary_to,
    )
    _apply_body(v, body)
    db.add(v)
    db.commit()
    return vac_out(db, v, employer_view=True)


@router.get(
    "/api/employer/vacancies",
    response_model=list[VacancyOut],
    summary="Мои вакансии",
    responses=responses(401, 403, 409),
)
def my_vacancies(user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    rows = db.scalars(
        select(Vacancy).where(Vacancy.company_id == company.id).order_by(Vacancy.updated_at.desc())
    ).all()
    return [vac_out(db, v, employer_view=True) for v in rows]


@router.put(
    "/api/employer/vacancies/{vacancy_id}",
    response_model=VacancyOut,
    summary="Редактировать вакансию",
    responses=responses(400, 401, 403, 404, 409, 422),
)
def update_vacancy(
    vacancy_id: str, body: VacancyIn, user: User = Depends(EmployerUser), db: Session = Depends(get_db)
):
    company = get_company(db, user)
    v = _own_vacancy(db, company, vacancy_id)
    _apply_body(v, body)
    db.commit()
    return vac_out(db, v, employer_view=True)


class ApplicationOut(BaseModel):
    id: str
    vacancy_id: str
    vacancy_title: str
    company_name: str
    status: str
    cover_letter: str | None
    employer_comment: str | None
    created_at: datetime
    updated_at: datetime
    candidate: CandidateCard | None = None
    match: dict | None = None


class ApplicationStatusIn(BaseModel):
    status: Literal["viewed", "interview", "rejected", "hired"]
    comment: str | None = Field(default=None, max_length=1000)


def app_out(db: Session, a: Application, *, with_candidate: bool) -> ApplicationOut:
    v = db.get(Vacancy, a.vacancy_id)
    c = db.get(Company, v.company_id) if v else None
    cand = None
    match = None
    if with_candidate:
        p = db.get(CandidateProfile, a.candidate_id)
        if p:
            cand = card(p, revealed=True)  # кандидат откликнулся сам — контакты открыты
            if v and p.specialization:
                s = score_candidate(
                    features(p),
                    vacancy_need(v),
                    utcnow().date(),
                )
                match = {
                    "score": s.score,
                    "reasons": [{"kind": r.kind, "text": r.text} for r in s.reasons],
                    "missing": s.missing,
                }
    return ApplicationOut(
        id=str(a.id),
        vacancy_id=str(a.vacancy_id),
        vacancy_title=v.title if v else "",
        company_name=c.name if c else "",
        status=a.status,
        cover_letter=a.cover_letter,
        employer_comment=a.employer_comment,
        created_at=a.created_at,
        updated_at=a.updated_at,
        candidate=cand,
        match=match,
    )


@router.get(
    "/api/employer/vacancies/{vacancy_id}/applications",
    response_model=list[ApplicationOut],
    summary="Отклики на вакансию",
    responses=responses(401, 403, 404, 409),
)
def vacancy_applications(vacancy_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    v = _own_vacancy(db, company, vacancy_id)
    rows = db.scalars(
        select(Application).where(Application.vacancy_id == v.id).order_by(Application.created_at.desc())
    ).all()
    out = [app_out(db, a, with_candidate=True) for a in rows]
    out.sort(key=lambda x: -(x.match or {}).get("score", 0))
    return out


@router.post(
    "/api/employer/applications/{app_id}/status",
    response_model=ApplicationOut,
    summary="Сменить статус отклика",
    responses=responses(401, 403, 404, 409),
)
def set_app_status(
    app_id: str, body: ApplicationStatusIn, user: User = Depends(EmployerUser), db: Session = Depends(get_db)
):
    company = get_company(db, user)
    try:
        a = db.get(Application, uuid.UUID(app_id))
    except ValueError:
        a = None
    v = db.get(Vacancy, a.vacancy_id) if a else None
    if a is None or v is None or v.company_id != company.id:
        raise not_found("Отклик")
    a.status = body.status
    a.employer_comment = body.comment
    db.commit()
    return app_out(db, a, with_candidate=True)


# ------------------------------------------------------------------------------------ кандидат


@router.get(
    "/api/vacancies",
    response_model=list[VacancyOut],
    summary="Лента вакансий (сортировка по соответствию профилю)",
    responses=responses(401, 403),
)
def feed(
    specialization: str | None = None,
    all_specializations: bool = False,
    q: str | None = Query(default=None, max_length=100),
    user: User = Depends(CandidateUser),
    db: Session = Depends(get_db),
):
    p = get_profile(db, user)
    query = select(Vacancy).where(Vacancy.status == "published")
    spec = specialization or (None if all_specializations else p.specialization)
    if spec:
        query = query.where(Vacancy.specialization == spec)
    rows = db.scalars(query).all()
    if q:
        ql = q.lower()
        rows = [v for v in rows if ql in v.title.lower() or ql in v.text.lower()]
    applied = set(
        db.scalars(select(Application.vacancy_id).where(Application.candidate_id == p.user_id)).all()
    )
    f = features(p)
    today = utcnow().date()
    scored = []
    for v in rows:
        match = None
        if p.specialization:
            # «обратный» подбор: та же формула, кандидат оценивается относительно вакансии
            f_spec = f if f.specialization == v.specialization else None
            if f_spec and p.confirmed_grade:
                s = score_candidate(
                    f,
                    vacancy_need(v),
                    today,
                )
                match = {
                    "score": s.score,
                    "reasons": [{"kind": r.kind, "text": r.text} for r in s.reasons if "ФСП" not in r.text][
                        :5
                    ],
                    "missing": s.missing,
                }
        scored.append((match["score"] if match else -1, v, match))
    scored.sort(key=lambda x: (-x[0], -x[1].created_at.timestamp()))
    return [vac_out(db, v, match=m, applied=v.id in applied) for _, v, m in scored]


@router.get(
    "/api/vacancies/{vacancy_id}",
    response_model=VacancyOut,
    summary="Вакансия",
    responses=responses(401, 403, 404),
)
def vacancy(vacancy_id: str, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    try:
        v = db.get(Vacancy, uuid.UUID(vacancy_id))
    except ValueError:
        v = None
    if v is None or v.status != "published":
        raise not_found("Вакансия")
    applied = (
        db.scalar(
            select(Application.id).where(Application.vacancy_id == v.id, Application.candidate_id == user.id)
        )
        is not None
    )
    return vac_out(db, v, applied=applied)


class ApplyIn(BaseModel):
    cover_letter: str | None = Field(default=None, max_length=5000)


@router.post(
    "/api/vacancies/{vacancy_id}/apply",
    response_model=ApplicationOut,
    status_code=201,
    summary="Откликнуться (контакты станут видны работодателю)",
    responses=responses(401, 403, 404, 409),
)
def apply(vacancy_id: str, body: ApplyIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    try:
        v = db.get(Vacancy, uuid.UUID(vacancy_id))
    except ValueError:
        v = None
    if v is None or v.status != "published":
        raise not_found("Вакансия")
    if not p.survey_completed_at:
        raise AppError(409, "survey_required", "Перед откликом пройдите опрос и заполните профиль")
    if db.scalar(
        select(Application.id).where(Application.vacancy_id == v.id, Application.candidate_id == p.user_id)
    ):
        raise conflict("already_applied", "Вы уже откликнулись на эту вакансию")
    a = Application(vacancy_id=v.id, candidate_id=p.user_id, cover_letter=body.cover_letter)
    db.add(a)
    p.last_active_at = utcnow()
    db.commit()
    return app_out(db, a, with_candidate=False)


@router.get(
    "/api/candidate/applications",
    response_model=list[ApplicationOut],
    summary="Мои отклики и их статусы",
    responses=responses(401, 403),
)
def my_applications(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Application).where(Application.candidate_id == user.id).order_by(Application.created_at.desc())
    ).all()
    return [app_out(db, a, with_candidate=False) for a in rows]


__all__ = ["router", "category_label"]
