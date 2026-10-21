from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends
from fspml.catalog import get_catalog
from fspml.matching.scoring import salary_fit
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.db import get_db, utcnow
from ...core.email import send_email
from ...core.errors import AppError, conflict, not_found, responses
from ...core.security import require_role
from ..candidates.models import CandidateProfile
from ..candidates.service import anonymous_alias, category_label, features, revealed_contacts
from ..employers.models import Company, Search
from ..employers.router import get_company
from ..employers.service import webhook_signing_key
from ..users.models import AuditLog, User
from ..vacancies.models import Application, Vacancy
from .models import ACCEPTED_STATUSES, Invitation

router = APIRouter(tags=["Приглашения"])
EmployerUser = require_role("employer")
CandidateUser = require_role("candidate")

ACTIVE = ("sent", "viewed")


class InvitationIn(BaseModel):
    candidate_id: str
    title: str = Field(min_length=3, max_length=255, description="Должность / суть предложения")
    description: str = Field(min_length=10, max_length=5000, description="Описание предложения")
    salary_from: int = Field(gt=0, le=10_000_000, description="Вилка ЗП «от», ₽ — обязательно")
    salary_to: int = Field(gt=0, le=10_000_000, description="Вилка ЗП «до», ₽ — обязательно")
    contact_method: Literal["email", "telegram", "phone", "other"]
    contact_value: str = Field(min_length=3, max_length=255)
    search_id: str | None = None
    vacancy_id: str | None = None

    @model_validator(mode="after")
    def _salary(self):
        if self.salary_to < self.salary_from:
            raise ValueError("верхняя граница вилки меньше нижней")
        return self


class InvitationOut(BaseModel):
    id: str
    status: str
    title: str
    description: str
    salary_from: int
    salary_to: int
    contact_method: str
    contact_value: str
    company_id: str
    company_name: str
    company_industry: str | None
    company_description: str | None
    company_stats: dict | None = None
    candidate_id: str
    candidate_alias: str
    candidate_category: str | None
    candidate_name: str | None = None
    candidate_contacts: dict | None = None
    vacancy_id: str | None
    search_id: str | None
    salary_fit: str | None
    decline_reason: str | None
    decline_comment: str | None
    created_at: datetime
    viewed_at: datetime | None
    responded_at: datetime | None


class SalaryCheckOut(BaseModel):
    fit: str = Field(
        description="within | partial | below | above | unknown — без раскрытия ожиданий кандидата"
    )
    message: str


class DeclineIn(BaseModel):
    reason: Literal["salary", "stack", "format", "company", "not_looking", "other"]
    comment: str | None = Field(default=None, max_length=1000)


def company_stats(db: Session, company_id: uuid.UUID) -> dict:
    since = utcnow() - timedelta(days=90)
    inv = db.execute(
        select(Invitation.status, func.count())
        .where(Invitation.company_id == company_id, Invitation.created_at >= since)
        .group_by(Invitation.status)
    ).all()
    counts = dict(inv)
    total = sum(counts.values())
    accepted = counts.get("accepted", 0) + counts.get("hired", 0)
    answered = accepted + counts.get("declined", 0)
    apps = db.execute(
        select(Application.status, func.count())
        .join(Vacancy, Vacancy.id == Application.vacancy_id)
        .where(Vacancy.company_id == company_id)
        .group_by(Application.status)
    ).all()
    ac = dict(apps)
    apps_total = sum(ac.values())
    apps_answered = apps_total - ac.get("sent", 0)
    return {
        "invitations_90d": total,
        "acceptance_rate": round(accepted / answered, 2) if answered else None,
        "application_response_rate": round(apps_answered / apps_total, 2) if apps_total else None,
    }


def inv_out(db: Session, inv: Invitation, *, for_employer: bool) -> InvitationOut:
    company = db.get(Company, inv.company_id)
    p = db.get(CandidateProfile, inv.candidate_id)
    revealed = for_employer and inv.status in ACCEPTED_STATUSES
    return InvitationOut(
        id=str(inv.id),
        status=inv.status,
        title=inv.title,
        description=inv.description,
        salary_from=inv.salary_from,
        salary_to=inv.salary_to,
        contact_method=inv.contact_method,
        contact_value=inv.contact_value,
        company_id=str(inv.company_id),
        company_name=company.name if company else "",
        company_industry=company.industry if company else None,
        company_description=company.description if company else None,
        company_stats=None if for_employer else company_stats(db, inv.company_id),
        candidate_id=str(inv.candidate_id),
        candidate_alias=anonymous_alias(p) if p else "",
        candidate_category=category_label(p) if p else None,
        candidate_name=revealed_contacts(p)[0] if (p and revealed) else None,
        candidate_contacts=revealed_contacts(p)[1] if (p and revealed) else None,
        vacancy_id=str(inv.vacancy_id) if inv.vacancy_id else None,
        search_id=str(inv.search_id) if inv.search_id else None,
        salary_fit=inv.salary_fit if for_employer else None,
        decline_reason=inv.decline_reason,
        decline_comment=inv.decline_comment,
        created_at=inv.created_at,
        viewed_at=inv.viewed_at,
        responded_at=inv.responded_at,
    )


FIT_MESSAGES = {
    "within": "Вилка в пределах ожиданий кандидата",
    "above": "Вилка выше ожиданий кандидата",
    "partial": "Вилка частично пересекается с ожиданиями — кандидат может отказаться по зарплате",
    "below": "Вилка ниже ожиданий кандидата — высокий риск отказа",
    "unknown": "Кандидат не указал ожидания по зарплате",
}


def _candidate_for_company(db: Session, company: Company, candidate_id: str) -> CandidateProfile:
    try:
        p = db.get(CandidateProfile, uuid.UUID(candidate_id))
    except ValueError:
        p = None
    if p is None or p.hidden or not p.confirmed_grade or str(company.id) in (p.excluded_companies or []):
        raise not_found("Кандидат")
    return p


@router.get(
    "/api/employer/salary-check",
    response_model=SalaryCheckOut,
    summary="Индикатор вилки до отправки приглашения",
    responses=responses(401, 403, 404, 409),
)
def salary_check(
    candidate_id: str,
    salary_from: int,
    salary_to: int,
    user: User = Depends(EmployerUser),
    db: Session = Depends(get_db),
):
    company = get_company(db, user)
    p = _candidate_for_company(db, company, candidate_id)
    fit = salary_fit(features(p), salary_from, salary_to)[1]
    return SalaryCheckOut(fit=fit, message=FIT_MESSAGES[fit])


def _notify_candidate(
    email: str | None, company_name: str, title: str, s_from: int, s_to: int, settings: Settings
) -> None:
    send_email(
        email or "",
        f"Приглашение от {company_name}",
        f"Компания «{company_name}» приглашает вас: {title}.\nВилка: {s_from:,}–{s_to:,} ₽.\n\nОткройте приглашения: {settings.frontend_url}/candidate/invitations".replace(
            ",", " "
        ),
    )


def _webhook(url: str, payload: dict, key: str) -> None:
    """ATS-интеграция: событие о принятом приглашении (best effort).

    Тело подписано: X-FSP-Signature: sha256=HMAC-SHA256(ключ компании, тело) — ключ виден работодателю
    в профиле компании (`webhook_signing_key`), ATS проверяет, что событие пришло от платформы."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    sig = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    try:
        httpx.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-FSP-Event": payload["event"],
                "X-FSP-Signature": f"sha256={sig}",
            },
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        pass


def accepted_payload(inv: Invitation, p: CandidateProfile) -> dict:
    """Событие invitation.accepted: кандидат дал согласие (принял приглашение) — контакты открыты."""
    name, contacts = revealed_contacts(p)
    return {
        "event": "invitation.accepted",
        "invitation_id": str(inv.id),
        "accepted_at": inv.responded_at.isoformat() if inv.responded_at else None,
        "title": inv.title,
        "salary": {"from": inv.salary_from, "to": inv.salary_to},
        "vacancy_id": str(inv.vacancy_id) if inv.vacancy_id else None,
        "candidate": {
            "id": str(p.user_id),
            "name": name,
            "email": contacts.get("email"),
            "phone": contacts.get("phone"),
            "telegram": contacts.get("telegram"),
            "github": contacts.get("github"),
            "category": category_label(p),
            "specialization": p.specialization,
            "grade": p.confirmed_grade,
            "fsp_id": p.fsp_id if p.show_fsp else None,
        },
    }


@router.post(
    "/api/employer/invitations",
    response_model=InvitationOut,
    status_code=201,
    summary="Пригласить кандидата (вилка обязательна)",
    responses=responses(401, 403, 404, 409, 422, 429),
)
def send_invitation(
    body: InvitationIn,
    bg: BackgroundTasks,
    user: User = Depends(EmployerUser),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    company = get_company(db, user)
    p = _candidate_for_company(db, company, body.candidate_id)
    if p.search_status == "closed":
        raise conflict("candidate_not_looking", "Кандидат сейчас не рассматривает предложения")
    dup = db.scalar(
        select(Invitation.id).where(
            Invitation.company_id == company.id,
            Invitation.candidate_id == p.user_id,
            Invitation.status.in_(ACTIVE),
        )
    )
    if dup:
        raise conflict("already_invited", "У этого кандидата уже есть ваше активное приглашение")
    week = (
        db.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(Invitation.company_id == company.id, Invitation.created_at >= utcnow() - timedelta(days=7))
        )
        or 0
    )
    if week >= settings.invite_quota_per_week:
        raise AppError(
            429, "quota_exceeded", f"Лимит {settings.invite_quota_per_week} приглашений в неделю исчерпан"
        )
    search_id = vacancy_id = None
    if body.search_id:
        s = db.get(Search, uuid.UUID(body.search_id))
        if s is None or s.company_id != company.id:
            raise not_found("Подборка")
        search_id = s.id
    if body.vacancy_id:
        v = db.get(Vacancy, uuid.UUID(body.vacancy_id))
        if v is None or v.company_id != company.id:
            raise not_found("Вакансия")
        vacancy_id = v.id
    fit = salary_fit(features(p), body.salary_from, body.salary_to)[1]
    inv = Invitation(
        company_id=company.id,
        candidate_id=p.user_id,
        search_id=search_id,
        vacancy_id=vacancy_id,
        title=body.title,
        description=body.description,
        salary_from=body.salary_from,
        salary_to=body.salary_to,
        contact_method=body.contact_method,
        contact_value=body.contact_value,
        salary_fit=fit,
    )
    db.add(inv)
    db.commit()
    bg.add_task(
        _notify_candidate,
        p.contact_email,
        company.name,
        body.title,
        body.salary_from,
        body.salary_to,
        settings,
    )
    return inv_out(db, inv, for_employer=True)


@router.get(
    "/api/employer/invitations",
    response_model=list[InvitationOut],
    summary="Отправленные приглашения и их статусы",
    responses=responses(401, 403, 409),
)
def employer_invitations(
    status: str | None = None, user: User = Depends(EmployerUser), db: Session = Depends(get_db)
):
    company = get_company(db, user)
    q = select(Invitation).where(Invitation.company_id == company.id)
    if status:
        q = q.where(Invitation.status == status)
    return [
        inv_out(db, i, for_employer=True) for i in db.scalars(q.order_by(Invitation.created_at.desc())).all()
    ]


@router.post(
    "/api/employer/invitations/{inv_id}/withdraw",
    response_model=InvitationOut,
    summary="Отозвать приглашение",
    responses=responses(401, 403, 404, 409),
)
def withdraw(inv_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    inv = _get_inv(db, inv_id)
    if inv.company_id != company.id:
        raise not_found("Приглашение")
    if inv.status not in ACTIVE:
        raise conflict("not_active", "Отозвать можно только активное приглашение")
    inv.status = "withdrawn"
    inv.responded_at = utcnow()
    db.commit()
    return inv_out(db, inv, for_employer=True)


@router.post(
    "/api/employer/invitations/{inv_id}/hired",
    response_model=InvitationOut,
    summary="Отметить, что кандидат вышел на работу (для воронки трудоустройства)",
    responses=responses(401, 403, 404, 409),
)
def mark_hired(inv_id: str, user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    company = get_company(db, user)
    inv = _get_inv(db, inv_id)
    if inv.company_id != company.id:
        raise not_found("Приглашение")
    if inv.status != "accepted":
        raise conflict("not_accepted", "Отметить выход на работу можно только по принятому приглашению")
    inv.status = "hired"
    inv.hired_at = utcnow()
    db.commit()
    return inv_out(db, inv, for_employer=True)


def _get_inv(db: Session, inv_id: str) -> Invitation:
    try:
        inv = db.get(Invitation, uuid.UUID(inv_id))
    except ValueError:
        inv = None
    if inv is None:
        raise not_found("Приглашение")
    return inv


# ----------------------------------------------------------------------------------- кандидат


@router.get(
    "/api/candidate/invitations",
    response_model=list[InvitationOut],
    summary="Входящие приглашения",
    responses=responses(401, 403),
)
def candidate_invitations(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Invitation)
        .where(Invitation.candidate_id == user.id, Invitation.status != "withdrawn")
        .order_by(Invitation.created_at.desc())
    ).all()
    return [inv_out(db, i, for_employer=False) for i in rows]


def _own_inv(db: Session, user: User, inv_id: str) -> Invitation:
    inv = _get_inv(db, inv_id)
    if inv.candidate_id != user.id:
        raise not_found("Приглашение")
    return inv


@router.get(
    "/api/candidate/invitations/{inv_id}",
    response_model=InvitationOut,
    summary="Открыть приглашение (статус → просмотрено)",
    responses=responses(401, 403, 404),
)
def view_invitation(inv_id: str, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    inv = _own_inv(db, user, inv_id)
    if inv.status == "sent":
        inv.status = "viewed"
        inv.viewed_at = utcnow()
        db.commit()
    return inv_out(db, inv, for_employer=False)


@router.post(
    "/api/candidate/invitations/{inv_id}/accept",
    response_model=InvitationOut,
    summary="Принять приглашение — контакты станут видны работодателю",
    responses=responses(401, 403, 404, 409),
)
def accept(
    inv_id: str,
    bg: BackgroundTasks,
    user: User = Depends(CandidateUser),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    inv = _own_inv(db, user, inv_id)
    if inv.status not in ACTIVE:
        raise conflict("not_active", "Приглашение уже обработано")
    now = utcnow()
    inv.viewed_at = inv.viewed_at or now
    inv.status = "accepted"
    inv.responded_at = now
    db.add(
        AuditLog(
            actor_id=user.id,
            action="contacts_revealed",
            subject_id=user.id,
            details={"company_id": str(inv.company_id), "invitation_id": str(inv.id)},
        )
    )
    db.commit()
    company = db.get(Company, inv.company_id)
    p = db.get(CandidateProfile, user.id)
    if company:
        owner = db.get(User, company.owner_id)
        bg.add_task(
            send_email,
            company.contact_email or (owner.email if owner else ""),
            f"Кандидат принял приглашение: {inv.title}",
            f"{revealed_contacts(p)[0] or 'Кандидат'} принял(а) ваше приглашение. Контакты доступны в карточке: {settings.frontend_url}/employer/invitations",
        )
        if company.webhook_url:
            bg.add_task(
                _webhook, company.webhook_url, accepted_payload(inv, p), webhook_signing_key(company.id)
            )
    return inv_out(db, inv, for_employer=False)


@router.post(
    "/api/candidate/invitations/{inv_id}/decline",
    response_model=InvitationOut,
    summary="Отклонить приглашение с причиной",
    responses=responses(401, 403, 404, 409, 422),
)
def decline(inv_id: str, body: DeclineIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    inv = _own_inv(db, user, inv_id)
    if inv.status not in ACTIVE:
        raise conflict("not_active", "Приглашение уже обработано")
    now = utcnow()
    inv.viewed_at = inv.viewed_at or now
    inv.status = "declined"
    inv.decline_reason = body.reason
    inv.decline_comment = body.comment
    inv.responded_at = now
    db.commit()
    return inv_out(db, inv, for_employer=False)


# ------------------------------------------------------------------------------ обратная связь


class InsightsOut(BaseModel):
    invitations: dict[str, int]
    decline_reasons: list[dict]
    acceptance_rate: float | None
    median_response_hours: float | None
    market: list[dict]


@router.get(
    "/api/employer/insights",
    response_model=InsightsOut,
    summary="Обратная связь рынка: причины отказов, ожидания по категориям",
    responses=responses(401, 403, 409),
)
def insights(user: User = Depends(EmployerUser), db: Session = Depends(get_db)):
    import numpy as np

    company = get_company(db, user)
    cat = get_catalog()
    rows = db.scalars(select(Invitation).where(Invitation.company_id == company.id)).all()
    statuses: dict[str, int] = {}
    for r in rows:
        statuses[r.status] = statuses.get(r.status, 0) + 1
    reasons: dict[str, int] = {}
    for r in rows:
        if r.status == "declined" and r.decline_reason:
            reasons[r.decline_reason] = reasons.get(r.decline_reason, 0) + 1
    total_declined = sum(reasons.values())
    titles = {x["id"]: x["title"] for x in cat.decline_reasons}
    accepted = statuses.get("accepted", 0) + statuses.get("hired", 0)
    answered = accepted + statuses.get("declined", 0)
    hours = [
        ((r.responded_at - r.created_at).total_seconds() / 3600)
        for r in rows
        if r.responded_at and r.status in (*ACCEPTED_STATUSES, "declined")
    ]
    # рынок: категории, в которых компания искала
    searched = db.execute(
        select(Search.specialization, Search.grade).where(Search.company_id == company.id).distinct()
    ).all()
    market = []
    for spec, grade in searched:
        pool = db.scalars(
            select(CandidateProfile).where(
                CandidateProfile.specialization == spec,
                CandidateProfile.confirmed_grade == grade,
                CandidateProfile.hidden.is_(False),
            )
        ).all()
        sal = sorted(p.salary_from for p in pool if p.salary_from)
        inv_cat = db.scalars(
            select(Invitation)
            .join(CandidateProfile, CandidateProfile.user_id == Invitation.candidate_id)
            .where(
                CandidateProfile.specialization == spec,
                CandidateProfile.confirmed_grade == grade,
                Invitation.status == "declined",
            )
        ).all()
        sal_decl = sum(1 for i in inv_cat if i.decline_reason == "salary")
        market.append(
            {
                "category": f"{cat.specializations[spec].name} · {cat.grade(grade).name}",
                "candidates": len(pool),
                "salary_p25": int(np.percentile(sal, 25)) if sal else None,
                "salary_median": int(np.median(sal)) if sal else None,
                "salary_p75": int(np.percentile(sal, 75)) if sal else None,
                "declines_total": len(inv_cat),
                "declines_salary_share": round(sal_decl / len(inv_cat), 2) if inv_cat else None,
            }
        )
    return InsightsOut(
        invitations=statuses,
        decline_reasons=[
            {"reason": k, "title": titles.get(k, k), "count": v, "share": round(v / total_declined, 2)}
            for k, v in sorted(reasons.items(), key=lambda x: -x[1])
        ],
        acceptance_rate=round(accepted / answered, 2) if answered else None,
        median_response_hours=round(float(np.median(hours)), 1) if hours else None,
        market=market,
    )


__all__ = ["router", "datetime"]
