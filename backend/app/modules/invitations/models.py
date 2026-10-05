from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base, new_id, utcnow


class Invitation(Base):
    """Приглашение от работодателя конкретному кандидату (механика «инициатива у работодателя»).

    Вилка «от–до» обязательна; контакты кандидата раскрываются только после статуса accepted.
    """

    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint("salary_from > 0 AND salary_to >= salary_from", name="salary_range"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.user_id", ondelete="CASCADE"), index=True
    )
    search_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("searches.id", ondelete="SET NULL"))
    vacancy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vacancies.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    contact_method: Mapped[str] = mapped_column(String(32))  # email | telegram | phone | other
    contact_value: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(16), default="sent", index=True
    )  # sent | viewed | accepted | declined | withdrawn
    decline_reason: Mapped[str | None] = mapped_column(String(32))
    decline_comment: Mapped[str | None] = mapped_column(String(1000))
    salary_fit: Mapped[str | None] = mapped_column(String(16))  # индикатор на момент отправки
    match_snapshot: Mapped[dict | None] = mapped_column(default=None)  # скор и объяснение на момент отправки
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    viewed_at: Mapped[datetime | None] = mapped_column(default=None)
    responded_at: Mapped[datetime | None] = mapped_column(default=None)
