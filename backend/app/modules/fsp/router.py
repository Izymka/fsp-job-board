"""Привязка ФСП ID (OAuth2/OIDC authorization code) и синхронизация достижений из реестра ФСП.

ФСП ID будет работать на Keycloak; в демо — отдельный realm `fsp-id`. Бэкенд выступает
OIDC-клиентом: при переходе на реальный ФСП ID меняются только issuer/client в конфигурации.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import urllib.parse
from datetime import timedelta

import httpx
import jwt
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.db import SessionLocal, aware, get_db, utcnow
from ...core.errors import AppError, conflict, responses
from ...core.security import require_role
from ..candidates.models import CandidateProfile
from ..candidates.router import ProfileOut, get_profile, profile_out
from ..users.models import User
from .client import RegistryUnavailable, fetch_participant, normalize_achievements

router = APIRouter(prefix="/api/fsp", tags=["ФСП"])
CandidateUser = require_role("candidate")
log = logging.getLogger("fsp")


class LinkStartOut(BaseModel):
    authorize_url: str


def _state(user_id: str, settings: Settings) -> str:
    payload = {
        "uid": user_id,
        "nonce": secrets.token_urlsafe(8),
        "exp": int(time.time()) + 600,
        "purpose": "fsp-link",
    }
    return jwt.encode(payload, settings.assessment_secret, algorithm="HS256")


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.public_api_url}/api/fsp/link/callback"


@router.get(
    "/link/start",
    response_model=LinkStartOut,
    summary="Начать привязку ФСП ID (редирект на страницу входа ФСП ID)",
    responses=responses(401, 403),
)
def link_start(user: User = Depends(CandidateUser), settings: Settings = Depends(get_settings)):
    params = {
        "client_id": settings.fsp_id_client_id,
        "response_type": "code",
        "scope": "openid profile",
        "redirect_uri": _redirect_uri(settings),
        "state": _state(str(user.id), settings),
        "prompt": "login",
    }
    url = (
        f"{settings.keycloak_public_url}/realms/{settings.fsp_id_realm}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(params)
    )
    return LinkStartOut(authorize_url=url)


def link_profile(db: Session, p: CandidateProfile, fsp_id: str) -> None:
    other = db.scalar(
        select(CandidateProfile).where(
            CandidateProfile.fsp_id == fsp_id, CandidateProfile.user_id != p.user_id
        )
    )
    if other is not None:
        raise conflict("fsp_id_taken", "Этот ФСП ID уже привязан к другому профилю")
    p.fsp_id = fsp_id
    p.fsp_linked_at = utcnow()
    sync_profile(p)


def sync_profile(p: CandidateProfile) -> bool:
    """Подтянуть достижения. Нет участника в реестре — история ФСП пуста (корректный случай)."""
    try:
        data = fetch_participant(p.fsp_id)
    except RegistryUnavailable as e:
        log.warning("registry unavailable for %s: %s", p.fsp_id, e)
        return False
    p.fsp_achievements = normalize_achievements(data)
    p.fsp_profile = {k: data.get(k) for k in ("full_name", "region", "sport_rank")} if data else None
    p.fsp_synced_at = utcnow()
    return True


@router.get(
    "/link/callback",
    include_in_schema=True,
    summary="Callback ФСП ID (браузерный редирект)",
    response_class=RedirectResponse,
    status_code=302,
)
def link_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    back = f"{settings.frontend_url}/candidate/settings"
    if error or not code or not state:
        return RedirectResponse(f"{back}?fsp=cancelled")
    try:
        st = jwt.decode(state, settings.assessment_secret, algorithms=["HS256"])
        if st.get("purpose") != "fsp-link":
            raise jwt.InvalidTokenError("purpose")
    except jwt.PyJWTError:
        return RedirectResponse(f"{back}?fsp=invalid_state")
    token_url = (
        f"{settings.keycloak_internal_url}/realms/{settings.fsp_id_realm}/protocol/openid-connect/token"
    )
    try:
        r = httpx.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(settings),
                "client_id": settings.fsp_id_client_id,
                "client_secret": settings.fsp_id_client_secret,
            },
            timeout=10,
        )
        r.raise_for_status()
        # id_token получен напрямую с token endpoint по серверному каналу → подпись можно не проверять повторно
        claims = jwt.decode(r.json()["id_token"], options={"verify_signature": False})
    except Exception as e:  # noqa: BLE001
        log.warning("fsp token exchange failed: %s", e)
        return RedirectResponse(f"{back}?fsp=error")
    raw_id = claims.get("fsp_id") or claims.get("preferred_username")
    fsp_id = str(raw_id).upper() if raw_id else None  # Keycloak хранит логины в нижнем регистре
    import uuid as _uuid

    user = db.get(User, _uuid.UUID(st["uid"]))
    if user is None or user.role != "candidate" or not fsp_id:
        return RedirectResponse(f"{back}?fsp=error")
    p = get_profile(db, user)
    try:
        link_profile(db, p, str(fsp_id))
    except AppError as e:
        return RedirectResponse(f"{back}?fsp={e.code}")
    db.commit()
    return RedirectResponse(f"{back}?fsp=linked")


class DemoLinkIn(BaseModel):
    fsp_id: str = Field(pattern=r"^FSP-\d{6}$")


@router.post(
    "/link/demo",
    response_model=ProfileOut,
    summary="Демо-привязка без ФСП ID (только AUTH_MODE=dev)",
    include_in_schema=False,
)
def link_demo(
    body: DemoLinkIn,
    user: User = Depends(CandidateUser),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if settings.auth_mode != "dev":
        raise AppError(404, "not_found", "Not found")
    p = get_profile(db, user)
    link_profile(db, p, body.fsp_id)
    db.commit()
    return profile_out(p)


@router.post(
    "/sync",
    response_model=ProfileOut,
    summary="Обновить достижения из реестра ФСП",
    responses=responses(401, 403, 409, 503),
)
def sync(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    if not p.fsp_id:
        raise conflict("fsp_not_linked", "ФСП ID не привязан")
    if not sync_profile(p):
        raise AppError(503, "registry_unavailable", "Реестр ФСП временно недоступен, попробуйте позже")
    db.commit()
    return profile_out(p)


@router.delete("/link", response_model=ProfileOut, summary="Отвязать ФСП ID", responses=responses(401, 403))
def unlink(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    p.fsp_id = None
    p.fsp_linked_at = p.fsp_synced_at = None
    p.fsp_achievements = []
    p.fsp_profile = None
    db.commit()
    return profile_out(p)


def sync_loop(stop: threading.Event) -> None:
    """Фоновая синхронизация привязанных профилей с реестром (по расписанию)."""
    s = get_settings()
    while not stop.wait(60):
        try:
            with SessionLocal() as db:
                cutoff = utcnow() - timedelta(hours=s.fsp_sync_interval_hours)
                rows = db.scalars(
                    select(CandidateProfile)
                    .where(
                        CandidateProfile.fsp_id.is_not(None),
                        or_(
                            CandidateProfile.fsp_synced_at.is_(None), CandidateProfile.fsp_synced_at < cutoff
                        ),
                    )
                    .limit(50)
                ).all()
                for p in rows:
                    if p.fsp_synced_at is None or aware(p.fsp_synced_at) < cutoff:
                        sync_profile(p)
                db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("fsp sync loop error: %s", e)
