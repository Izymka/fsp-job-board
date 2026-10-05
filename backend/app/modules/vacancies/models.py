from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base, TimestampMixin, new_id, utcnow


class Vacancy(TimestampMixin, Base):
    __tablename__ = "vacancies"
    __table_args__ = (CheckConstraint("salary_from > 0 AND salary_to >= salary_from", name="salary_range"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    specialization: Mapped[str] = mapped_column(String(32), index=True)
    grade: Mapped[str] = mapped_column(String(16))
    skills: Mapped[dict] = mapped_column(default=dict)
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    work_format: Mapped[str | None] = mapped_column(String(16))
    city: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16), default="published", index=True
    )  # draft | published | closed
    blueprint: Mapped[dict] = mapped_column(default=dict)
    parsed: Mapped[dict | None] = mapped_column(default=None)


class Application(Base):
    """Самостоятельный отклик кандидата (классический сценарий, дополнительный к приглашениям)."""

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("vacancy_id", "candidate_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vacancy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.user_id", ondelete="CASCADE"), index=True
    )
    cover_letter: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), default="sent", index=True
    )  # sent | viewed | interview | rejected | hired
    employer_comment: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
