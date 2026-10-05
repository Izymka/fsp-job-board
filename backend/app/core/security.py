"""Аутентификация по OIDC-токенам Keycloak (будущий ФСП ID) и ролевой доступ.

Токен проверяется локально по JWKS (подпись RS256, срок, issuer, audience). Пароли платформа
не хранит вовсе — это делает IdP. Роль (кандидат/работодатель) выбирается при первом входе и
хранится в нашей БД.

Режим AUTH_MODE=dev — только для локальной отладки и автотестов: токены HS256 выпускает сам
бэкенд (/api/dev/login). В production он выключен.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db, utcnow
from .errors import AppError

_jwks_client: jwt.PyJWKClient | None = None


def _jwks(settings: Settings) -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(settings.keycloak_jwks_url, cache_keys=True, lifespan=3600, timeout=5)
    return _jwks_client


def decode_token(token: str, settings: Settings) -> dict:
    try:
        if settings.auth_mode == "dev":
            return jwt.decode(
                token, settings.dev_jwt_secret, algorithms=["HS256"], audience=settings.keycloak_audience
            )
        key = _jwks(settings).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=settings.keycloak_issuer,
            options={"verify_aud": False},
            leeway=30,
        )
    except jwt.PyJWTError as e:
        raise AppError(401, "invalid_token", f"Недействительный токен: {e}") from e
    except Exception as e:  # недоступен JWKS и т.п.
        raise AppError(503, "idp_unavailable", "Сервис авторизации недоступен") from e
    aud = claims.get("aud") or []
    aud = [aud] if isinstance(aud, str) else aud
    if settings.keycloak_audience not in aud and claims.get("azp") != settings.keycloak_client_id:
        raise AppError(401, "invalid_audience", "Токен выпущен для другого приложения")
    return claims


def issue_dev_token(email: str, settings: Settings, sub: str | None = None) -> str:
    if settings.auth_mode != "dev":
        raise AppError(404, "not_found", "Not found")
    now = int(time.time())
    payload = {
        "sub": sub or f"dev:{email}",
        "email": email,
        "email_verified": True,
        "aud": settings.keycloak_audience,
        "iat": now,
        "exp": now + 12 * 3600,
        "preferred_username": email,
    }
    return jwt.encode(payload, settings.dev_jwt_secret, algorithm="HS256")


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    from ..modules.users.models import User

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "unauthorized", "Требуется вход в систему")
    claims = decode_token(authorization.split(" ", 1)[1], settings)
    if not claims.get("email_verified", False):
        raise AppError(403, "email_not_verified", "Подтвердите адрес электронной почты")
    sub = claims["sub"]
    user = db.scalar(select(User).where(User.subject == sub))
    if user is None and claims.get("email"):
        # предсозданный (seed) профиль с тем же подтверждённым email привязываем к учётной записи IdP
        user = db.scalar(select(User).where(User.email == claims["email"], User.subject.is_(None)))
        if user is not None:
            user.subject = sub
    if user is None:
        user = User(
            subject=sub,
            email=claims.get("email", ""),
            email_verified=True,
            display_name=claims.get("name") or claims.get("preferred_username"),
        )
        db.add(user)
        db.flush()
    now = utcnow()
    last = user.last_seen_at
    if last is None or (now - (last if last.tzinfo else last.replace(tzinfo=now.tzinfo))) > timedelta(
        minutes=5
    ):
        user.last_seen_at = now
    return user


def require_role(role: str):
    def dep(user=Depends(get_current_user)):
        if user.role != role:
            raise AppError(
                403,
                "wrong_role",
                "Раздел доступен только для роли: " + ("кандидат" if role == "candidate" else "работодатель"),
            )
        return user

    return dep


CurrentUser = Annotated[object, Depends(get_current_user)]
