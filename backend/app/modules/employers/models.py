from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base, TimestampMixin, new_id, utcnow


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(32))
    website: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(128))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    contact_telegram: Mapped[str | None] = mapped_column(String(64))
    inn: Mapped[str | None] = mapped_column(String(12))  # задел для верификации (вне MVP)
    webhook_url: Mapped[str | None] = mapped_column(String(500))  # ATS-интеграция


class Search(TimestampMixin, Base):
    """Потребность работодателя → сохранённая подборка. Фильтры версионируются (уточнение без потери)."""

    __tablename__ = "searches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text, default="")
    team_description: Mapped[str | None] = mapped_column(Text)
    specialization: Mapped[str] = mapped_column(String(32))
    grade: Mapped[str] = mapped_column(String(16))
    skills: Mapped[dict] = mapped_column(default=dict)  # технология → важность
    salary_from: Mapped[int | None] = mapped_column(default=None)
    salary_to: Mapped[int | None] = mapped_column(default=None)
    work_format: Mapped[str | None] = mapped_column(String(16))
    industry: Mapped[str | None] = mapped_column(String(32))
    min_years: Mapped[float | None] = mapped_column(default=None)  # требуемый опыт; None — по грейду
    include_adjacent: Mapped[bool] = mapped_column(default=True)
    fsp_friendly: Mapped[bool] = mapped_column(default=False, server_default="0")
    # уведомлять о новых участниках ФСП, попавших в топ подборки (см. `fsp_alerts`)
    notify_fsp: Mapped[bool] = mapped_column(default=False, server_default="0")
    parsed: Mapped[dict | None] = mapped_column(default=None)
    filters: Mapped[dict] = mapped_column(default=dict)
    version: Mapped[int] = mapped_column(default=1)
    embedding: Mapped[list | None] = mapped_column(default=None)


class SearchVersion(Base):
    __tablename__ = "search_versions"
    __table_args__ = (UniqueConstraint("search_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    search_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]
    filters: Mapped[dict] = mapped_column(default=dict)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ShortlistItem(Base):
    __tablename__ = "shortlist"
    __table_args__ = (UniqueConstraint("search_id", "candidate_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    search_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.user_id", ondelete="CASCADE")
    )
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FspMatchNotice(Base):
    """Участник ФСП попал в топ сохранённой подборки с `notify_fsp`: одна запись на пару, письмо —
    дайджестом не чаще раза в сутки на подборку (`emailed_at`)."""

    __tablename__ = "fsp_match_notices"
    __table_args__ = (UniqueConstraint("search_id", "candidate_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    search_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.user_id", ondelete="CASCADE")
    )
    rank: Mapped[int]
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    emailed_at: Mapped[datetime | None] = mapped_column(default=None)
