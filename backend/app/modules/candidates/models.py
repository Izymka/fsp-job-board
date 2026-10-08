from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base, TimestampMixin


class CandidateProfile(TimestampMixin, Base):
    """Профиль кандидата.

    Контактные данные (ФИО, телефон, email, telegram) хранятся здесь, но отдаются работодателю
    только после принятия приглашения или собственного отклика (см. invitations.access).
    Категория = specialization × confirmed_grade и задаётся только тестом.
    """

    __tablename__ = "candidate_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # личные данные (скрыты до контакта)
    full_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    telegram: Mapped[str | None] = mapped_column(String(64))
    github: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(128))
    # профессиональные данные
    headline: Mapped[str | None] = mapped_column(String(255))
    about: Mapped[str | None] = mapped_column(Text)
    experience_years: Mapped[float | None] = mapped_column(default=None)
    soft_skills: Mapped[list] = mapped_column(default=list)
    experience: Mapped[list] = mapped_column(default=list)  # [{title, start, end, description}]
    education: Mapped[str | None] = mapped_column(Text)
    resume_parsed: Mapped[dict | None] = mapped_column(default=None)
    # опрос
    survey_completed_at: Mapped[datetime | None] = mapped_column(default=None)
    industries: Mapped[list] = mapped_column(default=list)
    specialization: Mapped[str | None] = mapped_column(String(32), index=True)
    # направления внутри специализации (CV, NLP…): модули теста и сюжет практического кейса
    directions: Mapped[list] = mapped_column(default=list)
    stack: Mapped[list] = mapped_column(default=list)  # заявленные технологии
    work_formats: Mapped[list] = mapped_column(default=list)
    salary_from: Mapped[int | None] = mapped_column(default=None)
    salary_to: Mapped[int | None] = mapped_column(default=None)
    search_status: Mapped[str] = mapped_column(String(16), default="active")
    claimed_grade: Mapped[str | None] = mapped_column(String(16))
    # результат тестирования → категория
    confirmed_grade: Mapped[str | None] = mapped_column(String(16), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(default=None)
    last_grade_change_at: Mapped[datetime | None] = mapped_column(default=None)
    theta: Mapped[float | None] = mapped_column(default=None)
    theta_se: Mapped[float | None] = mapped_column(default=None)
    skill_scores: Mapped[dict] = mapped_column(default=dict)  # навык → {status, theta, se, n}
    # сводка последнего подтверждения: надёжность прохождения и практический кейс (для работодателя)
    assessment_summary: Mapped[dict | None] = mapped_column(default=None)
    # регулярные задания
    tasks_score: Mapped[float] = mapped_column(default=0.0)
    task_skills: Mapped[dict] = mapped_column(default=dict)
    # ФСП
    fsp_id: Mapped[str | None] = mapped_column(String(64), index=True)
    fsp_linked_at: Mapped[datetime | None] = mapped_column(default=None)
    fsp_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    fsp_profile: Mapped[dict | None] = mapped_column(default=None)  # {name, rank, region}
    fsp_achievements: Mapped[list] = mapped_column(default=list)
    # приватность
    show_fsp: Mapped[bool] = mapped_column(default=True)
    excluded_industries: Mapped[list] = mapped_column(default=list)
    excluded_companies: Mapped[list] = mapped_column(default=list)
    hidden: Mapped[bool] = mapped_column(default=False)  # согласие на публикацию отозвано
    # служебное
    last_active_at: Mapped[datetime | None] = mapped_column(default=None)
    embedding: Mapped[list | None] = mapped_column(default=None)
    embedding_model: Mapped[str | None] = mapped_column(String(64))
