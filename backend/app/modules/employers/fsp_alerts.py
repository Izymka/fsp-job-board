"""Подписка работодателя на новых участников ФСП (talent-pool alerts).

Событие — у кандидата с ФСП подтверждён грейд или обновились достижения из реестра. Кандидат
пересчитывается в сохранённых подборках той же специализации с включённым `notify_fsp`; если он
попал в топ-`TOP_N`, создаётся запись `FspMatchNotice` (одна на пару «подборка — кандидат»).
Работодатель получает дайджест не чаще раза в сутки на подборку: письмо и, если настроен вебхук,
событие `candidate.fsp_match` — без контактов, только ссылка на анонимную карточку и причина.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import aware, utcnow
from ...core.email import send_email
from ..candidates.models import CandidateProfile
from ..users.models import User
from . import service
from .models import Company, FspMatchNotice, Search

log = logging.getLogger("fsp_alerts")
TOP_N = 10
DIGEST_EVERY = timedelta(hours=24)


def on_fsp_candidate_update(db: Session, p: CandidateProfile) -> list[FspMatchNotice]:
    """Вызывается после подтверждения грейда или синхронизации с реестром. Возвращает новые записи."""
    if not (p.fsp_id and p.show_fsp and p.fsp_achievements and p.confirmed_grade and not p.hidden):
        return []
    searches = db.scalars(
        select(Search).where(Search.notify_fsp, Search.specialization == p.specialization)
    ).all()
    known = set(
        db.scalars(select(FspMatchNotice.search_id).where(FspMatchNotice.candidate_id == p.user_id)).all()
    )
    created = []
    db.flush()  # кандидат должен быть виден в подборке с новым грейдом и достижениями
    for s in searches:
        if s.id in known:
            continue
        company = db.get(Company, s.company_id)
        if company is None:
            continue
        res = service.run_search(db, company, s, limit=TOP_N)
        for rank, r in enumerate(res["results"], start=1):
            if r.card.id == str(p.user_id):
                reason = next((x.text for x in r.reasons if x.kind == "positive" and "ФСП" in x.text), None)
                reason = reason or next((x.text for x in r.reasons if x.kind == "positive"), "")
                n = FspMatchNotice(search_id=s.id, candidate_id=p.user_id, rank=rank, reason=reason[:500])
                db.add(n)
                created.append(n)
                break
    if created:
        db.flush()
        for sid in {n.search_id for n in created}:
            send_digest(db, db.get(Search, sid))
    return created


def send_digest(db: Session, s: Search) -> bool:
    """Отправить неотправленные уведомления подборки, если с прошлого письма прошли сутки."""
    pending = db.scalars(
        select(FspMatchNotice)
        .where(FspMatchNotice.search_id == s.id, FspMatchNotice.emailed_at.is_(None))
        .order_by(FspMatchNotice.rank)
    ).all()
    if not pending:
        return False
    last = db.scalar(
        select(FspMatchNotice.emailed_at)
        .where(FspMatchNotice.search_id == s.id, FspMatchNotice.emailed_at.is_not(None))
        .order_by(FspMatchNotice.emailed_at.desc())
        .limit(1)
    )
    now = utcnow()
    if last is not None and now - aware(last) < DIGEST_EVERY:
        return False
    company = db.get(Company, s.company_id)
    owner = db.get(User, company.owner_id) if company else None
    to = (company.contact_email if company else None) or (owner.email if owner else "")
    url = get_settings().frontend_url
    lines = [
        f"В подборке «{s.title}» появились участники ФСП с подтверждённым грейдом:",
        "",
        *[
            f"• {n.rank}-е место: {service.anonymous_alias(db.get(CandidateProfile, n.candidate_id))}"
            f"{' — ' + n.reason if n.reason else ''}\n  {url}/employer/candidates/{n.candidate_id}?search={s.id}"
            for n in pending
        ],
        "",
        f"Подборка: {url}/employer/searches/{s.id}",
        "Отключить уведомления можно на странице подборки.",
    ]
    send_email(to, f"Новые участники ФСП в подборке «{s.title}»", "\n".join(lines))
    if company and company.webhook_url:
        from ..invitations.router import _webhook
        from .service import webhook_signing_key

        for n in pending:
            _webhook(
                company.webhook_url,
                {
                    "event": "candidate.fsp_match",
                    "search_id": str(s.id),
                    "candidate_id": str(n.candidate_id),
                    "rank": n.rank,
                    "reason": n.reason,
                    "created_at": aware(n.created_at).isoformat(),
                },
                webhook_signing_key(company.id),
            )
    for n in pending:
        n.emailed_at = now
    return True


def send_due_digests(db: Session) -> int:
    """Фоновая отправка отложенных дайджестов (сутки с прошлого письма прошли)."""
    ids = set(db.scalars(select(FspMatchNotice.search_id).where(FspMatchNotice.emailed_at.is_(None))).all())
    sent = 0
    for sid in ids:
        s = db.get(Search, sid)
        if s is not None and s.notify_fsp and send_digest(db, s):
            sent += 1
    return sent
