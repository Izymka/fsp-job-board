from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.db import get_db, utcnow
from ...core.errors import AppError, conflict, responses
from ...core.security import get_current_user, issue_dev_token
from ..assessment.proctoring import delete_snapshots
from ..biometrics.provider import get_provider
from ..candidates.models import CandidateProfile
from ..employers.models import Company
from .models import Consent, User

router = APIRouter(tags=["Пользователь"])

CONSENT_TEXTS = {
    "pd_processing": "Согласие на обработку персональных данных в соответствии с Федеральным законом № 152-ФЗ «О персональных данных» "
    "для целей подбора работы: ФИО, контакты, сведения об образовании, опыте, навыках, результатах тестирования и достижениях ФСП.",
    "profile_publication": "Согласие на публикацию обезличенного профиля (специализация, грейд, навыки, результаты тестирования, "
    "достижения ФСП) для работодателей платформы. Контактные данные раскрываются только после принятия приглашения или отклика.",
    "proctoring_biometric": "Согласие на обработку биометрических персональных данных (ст. 11 Федерального закона № 152-ФЗ) "
    "для теста с цифровым проктором. Цель — подтвердить, что все попытки теста проходит владелец профиля. "
    "Видео и звук обрабатываются только на вашем устройстве и не передаются. Платформа получает числовой "
    "отпечаток лица (эмбеддинг, не изображение) и хранит его в зашифрованном виде как эталон для сверки "
    "один-к-одному с вашими следующими попытками; поиск по базе лиц не выполняется. Эталон удаляется при отзыве "
    "согласия. Согласие добровольно: без него тест можно пройти без проктора.",
    "proctoring_photo": "Согласие на передачу одного кадра с камеры, снятого при проверке перед тестом с проктором, "
    "работодателю, чьё приглашение вы приняли или на чью вакансию откликнулись, — чтобы он мог убедиться на "
    "собеседовании, что тест проходили вы. Кадр хранится 180 дней и удаляется раньше при отзыве согласия.",
}


class MeOut(BaseModel):
    id: str
    email: str
    role: str | None
    display_name: str | None
    consents: dict[str, bool]
    has_profile: bool
    has_company: bool
    onboarding_step: str


class RoleIn(BaseModel):
    role: Literal["candidate", "employer"]
    accept_pd_processing: bool
    accept_profile_publication: bool = False


class ConsentIn(BaseModel):
    kind: Literal["pd_processing", "profile_publication", "proctoring_biometric", "proctoring_photo"]
    accepted: bool


class DevLoginIn(BaseModel):
    email: EmailStr


class DevLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthConfigOut(BaseModel):
    mode: str
    keycloak_url: str
    realm: str
    client_id: str
    consent_version: str
    consent_texts: dict[str, str]


def _active_consents(db: Session, user: User) -> dict[str, bool]:
    rows = db.scalars(select(Consent).where(Consent.user_id == user.id, Consent.revoked_at.is_(None))).all()
    kinds = {r.kind for r in rows}
    return {k: k in kinds for k in CONSENT_TEXTS}


def _onboarding_step(db: Session, user: User) -> str:
    if not user.role:
        return "choose_role"
    if user.role == "fsp_admin":
        return "done"
    if user.role == "employer":
        return "done" if db.scalar(select(Company).where(Company.owner_id == user.id)) else "company"
    p = db.get(CandidateProfile, user.id)
    if p is None or not p.survey_completed_at:
        return "survey"
    if not p.confirmed_grade:
        return "test"
    return "done"


def me_out(db: Session, user: User) -> MeOut:
    return MeOut(
        id=str(user.id),
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        consents=_active_consents(db, user),
        has_profile=db.get(CandidateProfile, user.id) is not None,
        has_company=db.scalar(select(Company.id).where(Company.owner_id == user.id)) is not None,
        onboarding_step=_onboarding_step(db, user),
    )


@router.get("/api/auth/config", response_model=AuthConfigOut, summary="Параметры авторизации для фронтенда")
def auth_config(settings: Settings = Depends(get_settings)):
    return AuthConfigOut(
        mode=settings.auth_mode,
        keycloak_url=settings.keycloak_public_url,
        realm=settings.keycloak_realm,
        client_id=settings.keycloak_client_id,
        consent_version=settings.consent_version,
        consent_texts=CONSENT_TEXTS,
    )


@router.post("/api/dev/login", response_model=DevLoginOut, include_in_schema=False)
def dev_login(body: DevLoginIn, settings: Settings = Depends(get_settings)):
    """Только AUTH_MODE=dev: выдаёт тестовый токен без Keycloak (локальная отладка, автотесты)."""
    return DevLoginOut(access_token=issue_dev_token(body.email, settings))


@router.get(
    "/api/me", response_model=MeOut, summary="Текущий пользователь и шаг онбординга", responses=responses(401)
)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return me_out(db, user)


def _set_consent(db: Session, user: User, kind: str, accepted: bool, ip: str | None, version: str) -> None:
    active = db.scalars(
        select(Consent).where(Consent.user_id == user.id, Consent.kind == kind, Consent.revoked_at.is_(None))
    ).all()
    if accepted and not active:
        # повторное согласие после отзыва: запись той же версии текста активируется заново
        # (уникальность user/kind/version), иначе — новая запись
        prev = db.scalar(
            select(Consent).where(
                Consent.user_id == user.id, Consent.kind == kind, Consent.version == version
            )
        )
        if prev is not None:
            prev.accepted_at, prev.revoked_at, prev.ip = utcnow(), None, ip
        else:
            db.add(Consent(user_id=user.id, kind=kind, version=version, ip=ip))
    if not accepted:
        for c in active:
            c.revoked_at = utcnow()


@router.post(
    "/api/me/role",
    response_model=MeOut,
    summary="Выбор роли при первом входе",
    responses=responses(400, 401, 409),
)
def choose_role(
    body: RoleIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if user.role and user.role != body.role:
        raise conflict(
            "role_already_set", "Роль уже выбрана; для другой роли используйте отдельную учётную запись"
        )
    if not body.accept_pd_processing:
        raise AppError(
            400,
            "consent_required",
            "Без согласия на обработку персональных данных работа с платформой невозможна",
        )
    user.role = body.role
    ip = request.client.host if request.client else None
    _set_consent(db, user, "pd_processing", True, ip, settings.consent_version)
    if body.role == "candidate":
        _set_consent(
            db, user, "profile_publication", body.accept_profile_publication, ip, settings.consent_version
        )
        if db.get(CandidateProfile, user.id) is None:
            db.add(
                CandidateProfile(
                    user_id=user.id,
                    contact_email=user.email,
                    hidden=not body.accept_profile_publication,
                    last_active_at=utcnow(),
                )
            )
    db.commit()
    return me_out(db, user)


@router.post(
    "/api/me/consents", response_model=MeOut, summary="Дать или отозвать согласие", responses=responses(401)
)
def set_consent(
    body: ConsentIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _set_consent(
        db,
        user,
        body.kind,
        body.accepted,
        request.client.host if request.client else None,
        settings.consent_version,
    )
    if not body.accepted and body.kind == "proctoring_biometric":
        get_provider(settings).delete(db, user.id)
    if not body.accepted and body.kind == "proctoring_photo":
        delete_snapshots(db, user.id)
    if user.role == "candidate":
        p = db.get(CandidateProfile, user.id)
        if p is not None and body.kind in ("profile_publication", "pd_processing"):
            db.flush()
            consents = _active_consents(db, user)
            p.hidden = not (consents["profile_publication"] and consents["pd_processing"])
    db.commit()
    return me_out(db, user)


class ConsentRecord(BaseModel):
    kind: str
    version: str
    accepted_at: datetime
    revoked_at: datetime | None


@router.get(
    "/api/me/consents",
    response_model=list[ConsentRecord],
    summary="История согласий",
    responses=responses(401),
)
def consent_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Consent).where(Consent.user_id == user.id).order_by(Consent.accepted_at)).all()
    return [
        ConsentRecord(kind=r.kind, version=r.version, accepted_at=r.accepted_at, revoked_at=r.revoked_at)
        for r in rows
    ]
