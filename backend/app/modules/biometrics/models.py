from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base, utcnow


class BiometricTemplate(Base):
    """Эталон лица для сверки 1:1 (только демо-поставщик; в production эталон хранит ЕБС).

    Хранится зашифрованный эмбеддинг — вектор, а не изображение. При отзыве согласия шифротекст
    стирается, а строка остаётся с числом регистраций: пересоздание эталона видно работодателю,
    иначе подставной сдающий мог бы незаметно занять место владельца профиля.
    """

    __tablename__ = "biometric_templates"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    model_version: Mapped[str | None] = mapped_column(String(64), default=None)
    enrollments: Mapped[int] = mapped_column(default=0)
    enrolled_at: Mapped[datetime | None] = mapped_column(default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)


class AttemptSnapshot(Base):
    """Кадр сдающего из проверки перед тестом: работодатель сверяет лицо на собеседовании."""

    __tablename__ = "attempt_snapshots"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.user_id", ondelete="CASCADE"), index=True
    )
    jpeg: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column()
