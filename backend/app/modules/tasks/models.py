from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base, new_id, utcnow


class RegularTask(Base):
    """Короткое регулярное задание от работодателя.

    kind=auto — задание из банка по навыку (экземпляр уникален для каждого кандидата, проверка
    автоматическая, результат обновляет подоценку навыка); kind=open — «предложите подход»,
    оценивает работодатель по рубрике.
    """

    __tablename__ = "regular_tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(8))  # auto | open
    specialization: Mapped[str] = mapped_column(String(32))
    skill: Mapped[str | None] = mapped_column(String(32))
    level: Mapped[int | None] = mapped_column(default=None)
    prompt: Mapped[str | None] = mapped_column(Text)
    rubric: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TaskAssignment(Base):
    __tablename__ = "task_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regular_tasks.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.user_id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[str | None] = mapped_column(String(64))
    seed: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(16), default="assigned"
    )  # assigned | submitted | reviewed | expired
    answer: Mapped[dict | None] = mapped_column(default=None)
    correct: Mapped[bool | None] = mapped_column(default=None)
    score: Mapped[float | None] = mapped_column(default=None)
    feedback: Mapped[str | None] = mapped_column(Text)
    assigned_at: Mapped[datetime] = mapped_column(default=utcnow)
    due_at: Mapped[datetime | None] = mapped_column(default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
