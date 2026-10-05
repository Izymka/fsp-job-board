"""Правило видимости контактов (ТЗ §2.2 п.2): работодатель видит контакты кандидата только после
того, как кандидат принял его приглашение или сам откликнулся на его вакансию."""

from __future__ import annotations

import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from ..vacancies.models import Application, Vacancy
from .models import Invitation


def contacts_revealed(db: Session, company_id: uuid.UUID, candidate_id: uuid.UUID) -> bool:
    accepted = db.scalar(
        select(
            exists().where(
                Invitation.company_id == company_id,
                Invitation.candidate_id == candidate_id,
                Invitation.status == "accepted",
            )
        )
    )
    if accepted:
        return True
    applied = db.scalar(
        select(
            exists().where(
                Application.candidate_id == candidate_id,
                Application.vacancy_id == Vacancy.id,
                Vacancy.company_id == company_id,
            )
        )
    )
    return bool(applied)


def revealed_set(db: Session, company_id: uuid.UUID, candidate_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not candidate_ids:
        return set()
    a = db.scalars(
        select(Invitation.candidate_id).where(
            Invitation.company_id == company_id,
            Invitation.status == "accepted",
            Invitation.candidate_id.in_(candidate_ids),
        )
    ).all()
    b = db.scalars(
        select(Application.candidate_id)
        .join(Vacancy, Vacancy.id == Application.vacancy_id)
        .where(Vacancy.company_id == company_id, Application.candidate_id.in_(candidate_ids))
    ).all()
    return set(a) | set(b)
