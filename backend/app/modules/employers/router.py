from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from fspml.catalog import get_catalog
from fspml.matching.scoring import profile_strength
from fspml.nlp.embed import get_embedder
from fspml.nlp.vacancy import parse_need
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...core.errors import AppError, not_found, responses
from ...core.security import require_role
from ..assessment import proctoring
from ..candidates.models import CandidateProfile
from ..candidates.pdf import render_profile_pdf
from ..candidates.service import features
from ..invitations.access import contacts_revealed, revealed_set
from ..users.models import AuditLog, User
from . import service
from .models import Company, Search, SearchVersion, ShortlistItem

router = APIRouter(prefix="/api/employer", tags=["Работодатель"])
EmployerUser = require_role("employer")
GRADES = Literal["intern", "junior", "middle", "senior", "lead"]


# ------------------------------------------------------------------------------------ компания


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    industry: str | None = None
    website: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_telegram: str | None = Field(default=None, max_length=64)
    inn: str | None = Field(default=None, pattern=r"^\d{10}(\d{2})?$")
    webhook_url: str | None = Field(default=None, max_length=500)


class CompanyOut(CompanyIn):
    id: str
    created_at: datetime


def get_company(db: Session, user: User, *, required: bool = True) -> Company | None:
    c = db.scalar(select(Company).where(Company.owner_id == user.id))
    if c is None and required:
        raise AppError(409, "company_required", "Сначала заполните профиль компании")
    return c


def company_out(c: Company) -> CompanyOut:
    return CompanyOut(
        id=str(c.id), created_at=c.created_at, **{k: getattr(c, k) for k in CompanyIn.model_fields}
    )


@router.get(
    "/company", response_model=CompanyOut | None, summary="Профиль компании", responses=responses(401, 403)
)
def read_company(user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    c = get_company(db, user, required=False)
    return company_out(c) if c else None


@router.put(
    "/company",
    response_model=CompanyOut,
    summary="Создать или обновить профиль компании",
    responses=responses(401, 403, 422),
)
def upsert_company(body: CompanyIn, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    c = get_company(db, user, required=False)
    if c is None:
        c = Company(owner_id=user.id, name=body.name)
        db.add(c)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return company_out(c)


# ------------------------------------------------------------------------- потребность и подборка


class NeedParseIn(BaseModel):
    text: str = Field(max_length=20000)
    title: str | None = Field(default=None, max_length=255)


class NeedParseOut(BaseModel):
    specialization: str | None
    spec_scores: dict[str, float]
    grade: str | None
    grade_reason: str | None
    skills: dict[str, float]
    must: list[str]
    plus: list[str]
    salary_from: int | None
    salary_to: int | None
    work_format: str | None
    min_years: float | None = None
    blueprint: dict[str, float]
    explanation: list[str]


@router.post(
    "/needs/parse",
    response_model=NeedParseOut,
    summary="Разобрать описание потребности (NLP): навыки, специализация, грейд",
    responses=responses(401, 403),
)
def parse(body: NeedParseIn, user: User = Depends(EmployerUser)):
    n = parse_need(body.text, body.title or "")
    return NeedParseOut(
        specialization=n.specialization,
        spec_scores={k: round(v, 3) for k, v in n.spec_scores.items()},
        grade=n.grade,
        grade_reason=n.grade_reason,
        skills={k: round(v, 2) for k, v in n.skills.items()},
        must=n.must,
        plus=n.plus,
        salary_from=n.salary_from,
        salary_to=n.salary_to,
        work_format=n.work_format,
        min_years=n.min_years,
        blueprint=n.blueprint,
        explanation=n.explanation,
    )


class Filters(BaseModel):
    grades: list[GRADES] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list, description="технологии, которые кандидат должен указать")
    confirmed_skills: list[str] = Field(default_factory=list, description="навыки, подтверждённые тестом")
    has_fsp: bool | None = None
    formats: list[Literal["office", "hybrid", "remote"]] = Field(default_factory=list)
    salary_fit_only: bool = False
    only_active: bool = False
    exclude_adjacent: bool = False
    min_score: float | None = Field(default=None, ge=0, le=1)
    cities: list[str] = Field(default_factory=list)


class SearchIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    text: str = Field(
        default="", max_length=20000, description="Какие специалисты нужны и чем занимается команда"
    )
    team_description: str | None = Field(default=None, max_length=5000)
    specialization: str | None = None
    grade: GRADES | None = None
    skills: dict[str, float] | None = Field(
        default=None, description="технология → важность 0..1; если не задано — из текста"
    )
    salary_from: int | None = Field(default=None, gt=0)
    salary_to: int | None = Field(default=None, gt=0)
    work_format: Literal["office", "hybrid", "remote"] | None = None
    industry: str | None = None
    min_years: float | None = Field(
        default=None, ge=0, le=20, description="требуемый опыт, лет; если не задано — из текста"
    )
    include_adjacent: bool = True

    @model_validator(mode="after")
    def _check(self):
        if self.salary_from and self.salary_to and self.salary_to < self.salary_from:
            raise ValueError("верхняя граница вилки меньше нижней")
        return self


class SearchSummary(BaseModel):
    id: str
    title: str
    specialization: str
    grade: str
    category: str
    version: int
    created_at: datetime
    updated_at: datetime
    shortlist: int
    filters: dict


class SearchOut(BaseModel):
    search: SearchSummary
    need: dict
    base_total: int
    filtered_total: int
    results: list[service.RankedCandidate]
    categories: list[dict]
    versions: list[dict]


def _summary(db: Session, s: Search) -> SearchSummary:
    cat = get_catalog()
    n = db.scalar(select(func.count()).select_from(ShortlistItem).where(ShortlistItem.search_id == s.id)) or 0
    return SearchSummary(
        id=str(s.id),
        title=s.title,
        specialization=s.specialization,
        grade=s.grade,
        category=f"{cat.specializations[s.specialization].name} · {cat.grade(s.grade).name}",
        version=s.version,
        created_at=s.created_at,
        updated_at=s.updated_at,
        shortlist=n,
        filters=s.filters or {},
    )


def _own_search(db: Session, company: Company, search_id: str) -> Search:
    try:
        s = db.get(Search, uuid.UUID(search_id))
    except ValueError:
        s = None
    if s is None or s.company_id != company.id:
        raise not_found("Подборка")
    return s


def search_out(db: Session, company: Company, s: Search) -> SearchOut:
    res = service.run_search(db, company, s)
    short = set(db.scalars(select(ShortlistItem.candidate_id).where(ShortlistItem.search_id == s.id)).all())
    for r in res["results"]:
        r.shortlisted = uuid.UUID(r.card.id) in short
    versions = db.scalars(
        select(SearchVersion).where(SearchVersion.search_id == s.id).order_by(SearchVersion.version)
    ).all()
    return SearchOut(
        search=_summary(db, s),
        need={
            "text": s.text,
            "team_description": s.team_description,
            "skills": s.skills,
            "salary_from": s.salary_from,
            "salary_to": s.salary_to,
            "work_format": s.work_format,
            "industry": s.industry,
            "min_years": s.min_years,
            "include_adjacent": s.include_adjacent,
            "explanation": (s.parsed or {}).get("explanation", []),
        },
        base_total=res["base_total"],
        filtered_total=res["filtered_total"],
        results=res["results"],
        categories=res["categories"],
        versions=[
            {
                "version": v.version,
                "filters": v.filters,
                "note": v.note,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
    )


@router.post(
    "/searches",
    response_model=SearchOut,
    status_code=201,
    summary="Описать потребность и получить подборку",
    responses=responses(400, 401, 403, 409, 422),
)
def create_search(body: SearchIn, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    n = parse_need("\n".join(x for x in (body.text, body.team_description or "") if x), body.title)
    spec = body.specialization or n.specialization
    grade = body.grade or n.grade
    if not spec or spec not in get_catalog().specializations:
        raise AppError(
            400, "specialization_required", "Не удалось определить специализацию — выберите её явно"
        )
    if not grade:
        raise AppError(400, "grade_required", "Не удалось определить грейд — выберите его явно")
    skills = body.skills if body.skills is not None else n.skills
    s = Search(
        company_id=company.id,
        title=body.title,
        text=body.text,
        team_description=body.team_description,
        specialization=spec,
        grade=grade,
        skills=skills,
        salary_from=body.salary_from or n.salary_from,
        salary_to=body.salary_to or n.salary_to,
        work_format=body.work_format or n.work_format,
        industry=body.industry or company.industry,
        min_years=body.min_years if body.min_years is not None else n.min_years,
        include_adjacent=body.include_adjacent,
        parsed={
            "spec_scores": n.spec_scores,
            "explanation": n.explanation,
            "blueprint": n.blueprint,
            "must": n.must,
            "plus": n.plus,
        },
        filters={},
        version=1,
    )
    db.add(s)
    db.flush()
    db.add(SearchVersion(search_id=s.id, version=1, filters={}, note="Исходная подборка"))
    db.commit()
    return search_out(db, company, s)


@router.get(
    "/searches",
    response_model=list[SearchSummary],
    summary="Мои подборки",
    responses=responses(401, 403, 409),
)
def list_searches(user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    rows = db.scalars(
        select(Search).where(Search.company_id == company.id).order_by(Search.updated_at.desc())
    ).all()
    return [_summary(db, s) for s in rows]


@router.get(
    "/searches/{search_id}",
    response_model=SearchOut,
    summary="Подборка с ранжированием и объяснениями",
    responses=responses(401, 403, 404, 409),
)
def get_search(search_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    return search_out(db, company, _own_search(db, company, search_id))


class FiltersIn(BaseModel):
    filters: Filters
    note: str | None = Field(default=None, max_length=255)


@router.put(
    "/searches/{search_id}/filters",
    response_model=SearchOut,
    summary="Уточнить фильтры (новая версия, прежние сохраняются)",
    responses=responses(401, 403, 404, 409),
)
def set_filters(
    search_id: str, body: FiltersIn, user: User = Depends(EmployerUser), db: Session = Depends(get_db)
):
    company = get_company(db, user)
    s = _own_search(db, company, search_id)
    s.version += 1
    s.filters = body.filters.model_dump(exclude_defaults=True)
    db.add(SearchVersion(search_id=s.id, version=s.version, filters=s.filters, note=body.note))
    db.commit()
    return search_out(db, company, s)


@router.post(
    "/searches/{search_id}/revert/{version}",
    response_model=SearchOut,
    summary="Откатить фильтры к версии",
    responses=responses(401, 403, 404, 409),
)
def revert(search_id: str, version: int, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    s = _own_search(db, company, search_id)
    v = db.scalar(
        select(SearchVersion).where(SearchVersion.search_id == s.id, SearchVersion.version == version)
    )
    if v is None:
        raise not_found("Версия")
    s.version += 1
    s.filters = dict(v.filters)
    db.add(
        SearchVersion(search_id=s.id, version=s.version, filters=s.filters, note=f"Откат к версии {version}")
    )
    db.commit()
    return search_out(db, company, s)


@router.delete(
    "/searches/{search_id}",
    status_code=204,
    summary="Удалить подборку",
    responses=responses(401, 403, 404, 409),
)
def delete_search(search_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    db.delete(_own_search(db, company, search_id))
    db.commit()
    return Response(status_code=204)


class ShortlistIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.put(
    "/searches/{search_id}/shortlist/{candidate_id}",
    status_code=204,
    summary="Закрепить кандидата в шорт-листе",
    responses=responses(401, 403, 404, 409),
)
def shortlist_add(
    search_id: str,
    candidate_id: str,
    body: ShortlistIn | None = None,
    user: User = Depends(EmployerUser),
    db: Session = Depends(get_db),
):
    company = get_company(db, user)
    s = _own_search(db, company, search_id)
    cid = _visible_candidate(db, candidate_id).user_id
    item = db.scalar(
        select(ShortlistItem).where(ShortlistItem.search_id == s.id, ShortlistItem.candidate_id == cid)
    )
    if item is None:
        db.add(ShortlistItem(search_id=s.id, candidate_id=cid, note=body.note if body else None))
    db.commit()
    return Response(status_code=204)


@router.delete(
    "/searches/{search_id}/shortlist/{candidate_id}",
    status_code=204,
    summary="Убрать из шорт-листа",
    responses=responses(401, 403, 404, 409),
)
def shortlist_remove(
    search_id: str, candidate_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)
):
    company = get_company(db, user)
    s = _own_search(db, company, search_id)
    try:
        cid = uuid.UUID(candidate_id)
    except ValueError as e:
        raise not_found("Кандидат") from e
    item = db.scalar(
        select(ShortlistItem).where(ShortlistItem.search_id == s.id, ShortlistItem.candidate_id == cid)
    )
    if item:
        db.delete(item)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------------------ банк кандидатов


def _visible_candidate(db: Session, candidate_id: str, company_id: uuid.UUID | None = None) -> CandidateProfile:
    try:
        p = db.get(CandidateProfile, uuid.UUID(candidate_id))
    except ValueError:
        p = None
    if p is None or p.hidden:
        raise not_found("Кандидат")
    # Отклик разрешён до теста: получатель уже имеет доступ к профилю и контактам.
    if not p.confirmed_grade and not (
        company_id is not None and contacts_revealed(db, company_id, p.user_id)
    ):
        raise not_found("Кандидат")
    return p


class CategoryCell(BaseModel):
    specialization: str
    grade: str
    label: str
    total: int
    with_fsp: int
    active: int


@router.get(
    "/categories",
    response_model=list[CategoryCell],
    summary="Категоризированная база: специализация × грейд",
    responses=responses(401, 403),
)
def categories(user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    cat = get_catalog()
    out = []
    profiles = service.visible_profiles(db)
    for spec in cat.specializations.values():
        for g in cat.grades:
            pool = [
                p
                for p in profiles
                if p.specialization == spec.id and p.confirmed_grade == g.id and p.search_status != "closed"
            ]
            out.append(
                CategoryCell(
                    specialization=spec.id,
                    grade=g.id,
                    label=f"{spec.name} · {g.name}",
                    total=len(pool),
                    with_fsp=sum(1 for p in pool if p.fsp_id and p.show_fsp and p.fsp_achievements),
                    active=sum(1 for p in pool if p.search_status == "active"),
                )
            )
    return out


class BankPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[service.CandidateCard]


@router.get(
    "/candidates",
    response_model=BankPage,
    summary="Поиск по банку кандидатов (порядок — сила подтверждённого профиля)",
    responses=responses(401, 403, 409),
)
def bank(
    specialization: str | None = None,
    grade: list[str] = Query(default=[]),
    skill: list[str] = Query(default=[], description="технологии стека (все должны быть указаны)"),
    confirmed_skill: list[str] = Query(default=[], description="навыки, подтверждённые тестом"),
    has_fsp: bool | None = None,
    work_format: list[str] = Query(default=[]),
    only_active: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(EmployerUser),
    db: Session = Depends(get_db),
):
    company = get_company(db, user)
    profiles = service.visible_profiles(db, specialization, grade or None)
    today = utcnow().date()
    rows = []
    for p in profiles:
        if str(company.id) in (p.excluded_companies or []) or (
            company.industry and company.industry in (p.excluded_industries or [])
        ):
            continue
        if p.search_status == "closed" or (only_active and p.search_status != "active"):
            continue
        if skill and not set(skill) <= set(p.stack or []):
            continue
        if confirmed_skill and not all(
            (p.skill_scores or {}).get(k, {}).get("status") == "confirmed" for k in confirmed_skill
        ):
            continue
        if has_fsp is True and not (p.fsp_id and p.show_fsp and p.fsp_achievements):
            continue
        if has_fsp is False and (p.fsp_id and p.show_fsp and p.fsp_achievements):
            continue
        if work_format and not set(work_format) & set(p.work_formats or []):
            continue
        rows.append((profile_strength(features(p), today)[0], p))
    rows.sort(key=lambda x: (-x[0], str(x[1].user_id)))
    pct = service._percentiles(profiles)
    chunk = rows[(page - 1) * page_size : page * page_size]
    revealed = revealed_set(db, company.id, [p.user_id for _, p in chunk])
    return BankPage(
        total=len(rows),
        page=page,
        page_size=page_size,
        items=[
            service.card(p, revealed=p.user_id in revealed, percentile=pct.get(p.user_id), today=today)
            for _, p in chunk
        ],
    )


@router.get(
    "/candidates/{candidate_id}",
    response_model=service.CandidateCard,
    summary="Карточка кандидата (контакты — после принятия приглашения или отклика)",
    responses=responses(401, 403, 404, 409),
)
def candidate_card(
    candidate_id: str,
    salary_from: int | None = None,
    salary_to: int | None = None,
    user: User = Depends(EmployerUser),
    db: Session = Depends(get_db),
):
    company = get_company(db, user)
    p = _visible_candidate(db, candidate_id, company.id)
    if str(company.id) in (p.excluded_companies or []):
        raise not_found("Кандидат")
    revealed = contacts_revealed(db, company.id, p.user_id)
    if revealed:
        db.add(
            AuditLog(
                actor_id=user.id,
                action="contacts_viewed",
                subject_id=p.user_id,
                details={"company_id": str(company.id)},
            )
        )
        db.commit()
    pct = service._percentiles(service.visible_profiles(db, p.specialization, [p.confirmed_grade]))
    offer = (salary_from, salary_to) if (salary_from or salary_to) else None
    c = service.card(p, revealed=revealed, percentile=pct.get(p.user_id), offer=offer)
    c.test_photo_available = revealed and proctoring.latest_snapshot(db, p.user_id) is not None
    return c


@router.get(
    "/candidates/{candidate_id}/test-photo",
    response_class=Response,
    summary="Кадр с теста с проктором — после принятого приглашения или отклика, при согласии кандидата",
    responses={200: {"content": {"image/jpeg": {}}}, **responses(401, 403, 404, 409)},
)
def candidate_test_photo(
    candidate_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)
):
    company = get_company(db, user)
    p = _visible_candidate(db, candidate_id, company.id)
    if not contacts_revealed(db, company.id, p.user_id):
        raise AppError(
            403,
            "photo_locked",
            "Кадр с теста доступен после того, как кандидат принял приглашение или откликнулся",
        )
    snap = proctoring.latest_snapshot(db, p.user_id)
    if snap is None:
        raise not_found("Кадр с теста")
    db.add(
        AuditLog(
            actor_id=user.id,
            action="test_photo_viewed",
            subject_id=p.user_id,
            details={"company_id": str(company.id), "attempt_id": str(snap.attempt_id)},
        )
    )
    db.commit()
    return Response(snap.jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.get(
    "/candidates/{candidate_id}/profile.pdf",
    response_class=Response,
    summary="PDF-профиль кандидата",
    responses={200: {"content": {"application/pdf": {}}}, **responses(401, 403, 404, 409)},
)
def candidate_pdf(candidate_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    p = _visible_candidate(db, candidate_id, company.id)
    revealed = contacts_revealed(db, company.id, p.user_id)
    return Response(
        render_profile_pdf(p, reveal_contacts=revealed),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="candidate.pdf"'},
    )


def embed_text(text: str):
    return get_embedder().encode([text])[0]
