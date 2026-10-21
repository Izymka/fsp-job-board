from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base, TimestampMixin, new_id, utcnow


class User(TimestampMixin, Base):
    """Пользователь платформы. Аутентификация — во внешнем IdP (Keycloak), здесь — роль и связи."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    subject: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)  # sub из токена IdP
    email: Mapped[str] = mapped_column(String(320), index=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    role: Mapped[str | None] = mapped_column(String(16))  # candidate | employer | fsp_admin (федерация)
    display_name: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = mapped_column(default=None)
    is_demo: Mapped[bool] = mapped_column(default=False)


class Consent(Base):
    """Согласия по 152-ФЗ: хранится версия текста и время; отзыв — отдельной меткой."""

    __tablename__ = "consents"
    __table_args__ = (UniqueConstraint("user_id", "kind", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # pd_processing | profile_publication
    version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    ip: Mapped[str | None] = mapped_column(String(64))


class AuditLog(Base):
    """Журнал доступа к персональным данным (раскрытие контактов и т.п.)."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    details: Mapped[dict] = mapped_column(default=dict)
