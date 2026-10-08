"""Цифровой проктор на стороне сервера: согласия, сверка лица 1:1, кадр для работодателя.

Детекторы (лицо, телефон, речь, микрофон) работают в браузере; сюда приходят счётчики по заданию и
эмбеддинг лица. Решение о совпадении с эталоном принимает сервер.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import utcnow
from ...core.errors import AppError
from ..biometrics.models import AttemptSnapshot
from ..biometrics.provider import get_provider
from ..users.models import Consent
from .models import Attempt

CONSENT_BIOMETRIC = "proctoring_biometric"
CONSENT_PHOTO = "proctoring_photo"
SNAPSHOT_MAX_BYTES = 200_000
# поля счётчиков, которые принимаются от клиента (остальное в AttemptItem.proctor пишет сервер)
SIGNAL_FIELDS = (
    "no_face_ms",
    "multi_face_ms",
    "phone_hits",
    "look_away_ms",
    "look_down_ms",
    "speech_ms",
    "cam_lost_ms",
    "mic_lost_ms",
)


@dataclass(frozen=True)
class ProctorStart:
    embeddings: Sequence[Sequence[float]]  # несколько качественных кадров с проверки
    model: str
    snapshot_b64: str | None = None


def has_consent(db: Session, user_id: uuid.UUID, kind: str) -> bool:
    return (
        db.scalar(
            select(Consent.id).where(
                Consent.user_id == user_id, Consent.kind == kind, Consent.revoked_at.is_(None)
            )
        )
        is not None
    )


def _decode_jpeg(b64: str) -> bytes:
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(b64, validate=True)
    except ValueError as e:
        raise AppError(422, "bad_snapshot", "Кадр должен быть JPEG в base64") from e
    if not data.startswith(b"\xff\xd8") or len(data) > SNAPSHOT_MAX_BYTES:
        raise AppError(422, "bad_snapshot", "Кадр должен быть JPEG до 200 КБ")
    return data


def start(db: Session, attempt: Attempt, s: ProctorStart) -> None:
    """Включить проктор попытки: сверить лицо с эталоном (или создать эталон) и сохранить кадр."""
    if not has_consent(db, attempt.candidate_id, CONSENT_BIOMETRIC):
        raise AppError(
            409,
            "consent_required",
            "Для теста с проктором нужно согласие на обработку биометрических данных",
        )
    provider = get_provider()
    if provider.has_template(db, attempt.candidate_id):
        # лучший из кадров проверки: один неудачный кадр не делает старт «чужим»
        best, v = max(
            ((e, provider.verify(db, attempt.candidate_id, e, s.model)) for e in s.embeddings),
            key=lambda ev: ev[1].similarity,
        )
        identity = {"status": v.status, "similarity": v.similarity, "re_enrolled": False}
        # уверенное совпадение пополняет эталон: свет, очки, причёска со временем меняются
        if v.match:
            provider.add(db, attempt.candidate_id, best, s.model)
    else:
        e = provider.enroll(db, attempt.candidate_id, s.embeddings, s.model)
        identity = {"status": "enrolled", "similarity": None, "re_enrolled": e.re_enrolled}
    attempt.proctored = True
    attempt.identity = {**identity, "provider": provider.name, "model": s.model}
    if s.snapshot_b64 and has_consent(db, attempt.candidate_id, CONSENT_PHOTO):
        purge_expired(db)
        days = get_settings().snapshot_retention_days
        db.add(
            AttemptSnapshot(
                attempt_id=attempt.id,
                candidate_id=attempt.candidate_id,
                jpeg=_decode_jpeg(s.snapshot_b64),
                expires_at=utcnow() + timedelta(days=days),
            )
        )


def item_signals(
    db: Session, attempt: Attempt, signals: dict | None, embedding: Sequence[float] | None
) -> dict | None:
    """Счётчики задания для AttemptItem.proctor + серверная сверка эмбеддинга, если он пришёл."""
    if not attempt.proctored:
        return None
    raw = signals or {}
    out = {k: max(0, int(raw.get(k) or 0)) for k in SIGNAL_FIELDS}
    out["checks"] = out["mismatch"] = out["uncertain"] = 0
    if embedding:
        model = (attempt.identity or {}).get("model", "")
        v = get_provider().verify(db, attempt.candidate_id, embedding, model)
        out["checks"] = 1
        out["mismatch"], out["uncertain"] = int(v.status == "mismatch"), int(v.status == "uncertain")
        # сходство хранится для калибровки порогов на реальных данных
        out["similarity"] = v.similarity
    return out


def purge_expired(db: Session) -> None:
    db.execute(delete(AttemptSnapshot).where(AttemptSnapshot.expires_at < utcnow()))


def delete_snapshots(db: Session, user_id: uuid.UUID) -> None:
    db.execute(delete(AttemptSnapshot).where(AttemptSnapshot.candidate_id == user_id))


def latest_snapshot(db: Session, user_id: uuid.UUID) -> AttemptSnapshot | None:
    purge_expired(db)
    return db.scalar(
        select(AttemptSnapshot)
        .where(AttemptSnapshot.candidate_id == user_id)
        .order_by(AttemptSnapshot.created_at.desc())
    )


def summary(attempt: Attempt, report) -> dict | None:
    """Что видит работодатель: статус проктора, сверка с эталоном, пересоздание эталона, причины."""
    if not attempt.proctored or report is None or report.proctoring is None:
        return None
    pr = report.proctoring
    ident = attempt.identity or {}
    return {
        "status": pr.status,
        "identity": ident.get("status"),
        "re_enrolled": bool(ident.get("re_enrolled")),
        "checks": pr.checks,
        "mismatches": pr.mismatches,
        "episodes": pr.episodes,
        "uncertain": pr.uncertain,
        "look_down_items": pr.look_down_items,
        "severity": pr.severity,
        "reasons": pr.reasons,
    }
