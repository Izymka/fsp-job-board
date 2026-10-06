from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from fspml.catalog import get_catalog
from fspml.nlp.resume import parse_resume_pdf, parse_resume_text
from fspml.nlp.skills import get_dictionary
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import get_db, utcnow
from ...core.errors import AppError, bad_request, responses
from ...core.security import require_role
from ..users.models import User
from .models import CandidateProfile
from .pdf import render_profile_pdf
from .service import category_label, update_embedding

router = APIRouter(prefix="/api/candidate", tags=["Кандидат: профиль"])
CandidateUser = require_role("candidate")

GRADES = Literal["intern", "junior", "middle", "senior", "lead"]


class JobIn(BaseModel):
    title: str = Field(max_length=200)
    start: str | None = Field(default=None, max_length=32)
    end: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=2000)


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    telegram: str | None = Field(default=None, max_length=64)
    github: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=128)
    headline: str | None = Field(default=None, max_length=255)
    about: str | None = Field(default=None, max_length=5000)
    experience_years: float | None = Field(default=None, ge=0, le=60)
    soft_skills: list[str] = Field(default_factory=list, max_length=30)
    experience: list[JobIn] = Field(default_factory=list, max_length=20)
    education: str | None = Field(default=None, max_length=2000)


class SurveyIn(BaseModel):
    """Обязательный опрос: отрасль, специализация, стек, условия, самооценка грейда."""

    industries: list[str] = Field(default_factory=list, max_length=6)
    specialization: str
    stack: list[str] = Field(default_factory=list, max_length=40)
    work_formats: list[Literal["office", "hybrid", "remote"]] = Field(min_length=1)
    salary_from: int = Field(gt=0, le=10_000_000)
    salary_to: int | None = Field(default=None, gt=0, le=10_000_000)
    search_status: Literal["active", "open", "closed"] = "active"
    claimed_grade: GRADES

    @field_validator("specialization")
    @classmethod
    def _spec(cls, v: str) -> str:
        if v not in get_catalog().specializations:
            raise ValueError("неизвестная специализация")
        return v

    @field_validator("industries")
    @classmethod
    def _ind(cls, v: list[str]) -> list[str]:
        known = {x["id"] for x in get_catalog().industries}
        bad = [x for x in v if x not in known]
        if bad:
            raise ValueError(f"неизвестные отрасли: {bad}")
        return v

    @model_validator(mode="after")
    def _salary(self):
        if self.salary_to is not None and self.salary_to < self.salary_from:
            raise ValueError("верхняя граница ожиданий меньше нижней")
        return self


class PrivacyIn(BaseModel):
    show_fsp: bool = True
    excluded_industries: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(
        default_factory=list, description="id компаний, от которых профиль скрыт"
    )
    search_status: Literal["active", "open", "closed"] | None = None


class SkillScoreOut(BaseModel):
    status: str
    theta: float | None = None
    se: float | None = None
    n: int = 0
    title: str = ""


class ProfileOut(BaseModel):
    user_id: str
    full_name: str | None
    contact_email: str | None
    phone: str | None
    telegram: str | None
    github: str | None
    city: str | None
    headline: str | None
    about: str | None
    experience_years: float | None
    soft_skills: list[str]
    experience: list[dict]
    education: str | None
    survey_completed_at: datetime | None
    industries: list[str]
    specialization: str | None
    stack: list[str]
    work_formats: list[str]
    salary_from: int | None
    salary_to: int | None
    search_status: str
    claimed_grade: str | None
    confirmed_grade: str | None
    confirmed_at: datetime | None
    category: str | None
    theta: float | None
    skill_scores: dict[str, SkillScoreOut]
    tasks_score: float
    fsp_id: str | None
    fsp_linked_at: datetime | None
    fsp_synced_at: datetime | None
    fsp_profile: dict | None
    fsp_achievements: list[dict]
    show_fsp: bool
    excluded_industries: list[str]
    excluded_companies: list[str]
    hidden: bool
    resume_parsed: dict | None


def get_profile(db: Session, user: User) -> CandidateProfile:
    p = db.get(CandidateProfile, user.id)
    if p is None:
        p = CandidateProfile(user_id=user.id, contact_email=user.email, last_active_at=utcnow())
        db.add(p)
        db.flush()
    return p


def profile_out(p: CandidateProfile) -> ProfileOut:
    cat = get_catalog()
    return ProfileOut(
        user_id=str(p.user_id),
        full_name=p.full_name,
        contact_email=p.contact_email,
        phone=p.phone,
        telegram=p.telegram,
        github=p.github,
        city=p.city,
        headline=p.headline,
        about=p.about,
        experience_years=p.experience_years,
        soft_skills=p.soft_skills or [],
        experience=p.experience or [],
        education=p.education,
        survey_completed_at=p.survey_completed_at,
        industries=p.industries or [],
        specialization=p.specialization,
        stack=p.stack or [],
        work_formats=p.work_formats or [],
        salary_from=p.salary_from,
        salary_to=p.salary_to,
        search_status=p.search_status,
        claimed_grade=p.claimed_grade,
        confirmed_grade=p.confirmed_grade,
        confirmed_at=p.confirmed_at,
        category=category_label(p),
        theta=p.theta,
        skill_scores={
            k: SkillScoreOut(**v, title=cat.assessment_skills.get(k, {}).get("title", k))
            for k, v in (p.skill_scores or {}).items()
        },
        tasks_score=p.tasks_score or 0.0,
        fsp_id=p.fsp_id,
        fsp_linked_at=p.fsp_linked_at,
        fsp_synced_at=p.fsp_synced_at,
        fsp_profile=p.fsp_profile,
        fsp_achievements=p.fsp_achievements or [],
        show_fsp=p.show_fsp,
        excluded_industries=p.excluded_industries or [],
        excluded_companies=p.excluded_companies or [],
        hidden=p.hidden,
        resume_parsed=p.resume_parsed,
    )


@router.get("/profile", response_model=ProfileOut, summary="Мой профиль", responses=responses(401, 403))
def read_profile(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    p.last_active_at = utcnow()
    db.commit()
    return profile_out(p)


@router.put(
    "/profile",
    response_model=ProfileOut,
    summary="Заполнить профиль вручную",
    responses=responses(401, 403, 422),
)
def update_profile(body: ProfileIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    p.experience = [j.model_dump() for j in body.experience]
    p.last_active_at = utcnow()
    update_embedding(p)
    db.commit()
    return profile_out(p)


def _normalize_stack(stack: list[str]) -> list[str]:
    """Приводим названия технологий к каноническим (алиасы и опечатки → словарь)."""
    dic = get_dictionary()
    out: list[str] = []
    for s in stack:
        s = s.strip()
        if not s:
            continue
        if s in dic.techs:
            name = s
        else:
            found = dic.extract(s)
            name = next(iter(found), s[:64])
        if name not in out:
            out.append(name)
    return out


@router.put(
    "/survey",
    response_model=ProfileOut,
    summary="Пройти/обновить обязательный опрос",
    responses=responses(401, 403, 422),
)
def survey(body: SurveyIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    if p.confirmed_grade and p.specialization and body.specialization != p.specialization:
        # Смена специализации = новая категория: прежний результат теста к ней не относится.
        p.confirmed_grade = None
        p.confirmed_at = None
        p.theta = p.theta_se = None
        p.skill_scores = {}
        p.assessment_summary = None
    p.industries = body.industries
    p.specialization = body.specialization
    p.stack = _normalize_stack(body.stack)
    p.work_formats = list(body.work_formats)
    p.salary_from, p.salary_to = body.salary_from, body.salary_to
    p.search_status = body.search_status
    p.claimed_grade = body.claimed_grade
    p.survey_completed_at = utcnow()
    p.last_active_at = utcnow()
    update_embedding(p)
    db.commit()
    return profile_out(p)


@router.put(
    "/privacy", response_model=ProfileOut, summary="Настройки приватности", responses=responses(401, 403)
)
def privacy(body: PrivacyIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    p.show_fsp = body.show_fsp
    p.excluded_industries = body.excluded_industries
    p.excluded_companies = body.excluded_companies
    if body.search_status:
        p.search_status = body.search_status
    db.commit()
    return profile_out(p)


class ResumeParseOut(BaseModel):
    parsed: dict
    suggestions: dict
    warnings: list[str]


@router.post(
    "/resume",
    response_model=ResumeParseOut,
    summary="Загрузить PDF-резюме и распознать поля",
    responses=responses(400, 401, 403),
)
async def upload_resume(
    file: UploadFile = File(...), user: User = Depends(CandidateUser), db: Session = Depends(get_db)
):
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise bad_request("file_too_large", "Файл больше 5 МБ")
    if data[:4] == b"%PDF":
        try:
            parsed = parse_resume_pdf(data, llm_fallback=get_settings().resume_llm_fallback)
        except Exception as e:  # noqa: BLE001
            raise bad_request("pdf_unreadable", "Не удалось прочитать PDF") from e
    elif (file.filename or "").lower().endswith(".txt"):
        parsed = parse_resume_text(
            data.decode("utf-8", errors="ignore"), llm_fallback=get_settings().resume_llm_fallback
        )
    else:
        raise bad_request("unsupported_format", "Поддерживается PDF (или .txt)")
    d = parsed.to_dict()
    p = get_profile(db, user)
    p.resume_parsed = d
    db.commit()
    suggestions = {
        "full_name": d["full_name"],
        "contact_email": d["email"],
        "phone": d["phone"],
        "telegram": d["telegram"],
        "github": d["github"],
        "city": d["city"],
        "about": d["about"],
        "headline": d["headline"],
        # для подбора важен стаж в IT; общий стаж — в grade_reason
        "experience_years": d["it_experience_years"] if d["jobs"] else d["experience_years"],
        "soft_skills": d["soft_skills"],
        "experience": [
            {"title": j["title"], "start": j["start"], "end": j["end"], "description": j["description"]}
            for j in d["jobs"]
        ],
        "stack": d["skills"][:30],
        "specialization": d["specialization_hint"],
        "claimed_grade": d["grade_hint"],
        "grade_reason": d["grade_reason"],
    }
    return ResumeParseOut(parsed=d, suggestions=suggestions, warnings=d["warnings"])


@router.get(
    "/profile.pdf",
    summary="Стандартизированный PDF-профиль",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, **responses(401, 403)},
)
def profile_pdf(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    pdf = render_profile_pdf(p, reveal_contacts=True)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="fsp-profile.pdf"'},
    )


class DashboardOut(BaseModel):
    category: str | None
    onboarding_step: str
    invitations_new: int
    invitations_total: int
    applications_total: int
    tasks_open: int
    fsp_linked: bool
    profile_completeness: float
    next_actions: list[str]


@router.get(
    "/dashboard",
    response_model=DashboardOut,
    summary="Сводка кабинета кандидата",
    responses=responses(401, 403),
)
def dashboard(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    from ..invitations.models import Invitation
    from ..tasks.models import TaskAssignment
    from ..vacancies.models import Application

    p = get_profile(db, user)
    inv_new = (
        db.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(Invitation.candidate_id == p.user_id, Invitation.status == "sent")
        )
        or 0
    )
    inv_total = (
        db.scalar(select(func.count()).select_from(Invitation).where(Invitation.candidate_id == p.user_id))
        or 0
    )
    apps = (
        db.scalar(select(func.count()).select_from(Application).where(Application.candidate_id == p.user_id))
        or 0
    )
    tasks = (
        db.scalar(
            select(func.count())
            .select_from(TaskAssignment)
            .where(TaskAssignment.candidate_id == p.user_id, TaskAssignment.status == "assigned")
        )
        or 0
    )
    fields = [p.full_name, p.city, p.headline, p.about, p.stack, p.experience, p.salary_from, p.work_formats]
    completeness = sum(1 for f in fields if f) / len(fields)
    step = "survey" if not p.survey_completed_at else ("test" if not p.confirmed_grade else "done")
    actions = []
    if step == "survey":
        actions.append("Пройдите опрос: специализация, стек и ожидания")
    elif step == "test":
        actions.append("Пройдите тест на заявленный грейд — после него профиль увидят работодатели")
    if not p.fsp_id:
        actions.append("Привяжите ФСП ID, чтобы показать достижения в соревнованиях")
    if completeness < 0.75:
        actions.append("Дополните профиль или загрузите PDF-резюме")
    if inv_new:
        actions.append(f"Новых приглашений: {inv_new}")
    if p.hidden:
        actions.append("Профиль скрыт: дайте согласие на публикацию в настройках")
    return DashboardOut(
        category=category_label(p),
        onboarding_step=step,
        invitations_new=inv_new,
        invitations_total=inv_total,
        applications_total=apps,
        tasks_open=tasks,
        fsp_linked=bool(p.fsp_id),
        profile_completeness=round(completeness, 2),
        next_actions=actions,
    )


__all__ = ["router", "get_profile", "profile_out", "AppError"]
