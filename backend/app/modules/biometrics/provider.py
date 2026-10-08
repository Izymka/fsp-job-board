"""Сверка лица 1:1 с эталоном профиля.

Эмбеддинг считает браузер кандидата (Human, модель faceres); сервер получает только вектор и
решает сам — клиентскому флагу «совпало» не доверяем. Поиска по базе (1:N) нет.

Поставщики:
* `local_demo` — эталон в нашей БД, зашифрован AES-256-GCM. Только для демонстрации.
* `ebs` — Единая биометрическая система. По 572-ФЗ аутентификация по биометрии в production
  идёт через ЕБС или аккредитованные системы; здесь — точка интеграции.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.db import utcnow
from ...core.errors import AppError
from .models import BiometricTemplate

EMBEDDING_MIN, EMBEDDING_MAX = 64, 2048


@dataclass(frozen=True)
class Verification:
    match: bool
    similarity: float


@dataclass(frozen=True)
class Enrollment:
    re_enrolled: bool  # эталон уже создавался раньше и был удалён (отзыв согласия)


class BiometricProvider(Protocol):
    name: str

    def has_template(self, db: Session, user_id: uuid.UUID) -> bool: ...

    def enroll(
        self, db: Session, user_id: uuid.UUID, embedding: Sequence[float], model: str
    ) -> Enrollment: ...

    def verify(
        self, db: Session, user_id: uuid.UUID, embedding: Sequence[float], model: str
    ) -> Verification: ...

    def delete(self, db: Session, user_id: uuid.UUID) -> bool: ...


def check_embedding(embedding: Sequence[float]) -> list[float]:
    v = [float(x) for x in embedding]
    if not EMBEDDING_MIN <= len(v) <= EMBEDDING_MAX or not all(math.isfinite(x) for x in v):
        raise AppError(422, "bad_embedding", "Некорректный эмбеддинг лица")
    return v


def similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Сходство как `human.match.similarity` с параметрами по умолчанию (src/face/match.ts): 0..1.

    dist = 25·Σ(aᵢ − bᵢ)², затем (1 − √dist / 100 − 0.2) / (0.8 − 0.2), обрезка в [0, 1].
    По документации Human сходство выше 0.5 можно считать совпадением.
    """
    if len(a) != len(b):
        return 0.0
    dist = round(100 * 25 * sum((x - y) ** 2 for x, y in zip(a, b))) / 100
    if dist == 0:
        return 1.0
    norm = (1 - math.sqrt(dist) / 100 - 0.2) / (0.8 - 0.2)
    return round(100 * min(1.0, max(0.0, norm))) / 100


class LocalDemoProvider:
    name = "local_demo"

    def __init__(self, settings: Settings) -> None:
        self.key = hashlib.sha256(settings.biometric_key.encode()).digest()
        self.threshold = settings.biometric_threshold

    def _pack(self, v: Sequence[float], model: str) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        data = struct.pack(f"<{len(v)}f", *v)
        return AESGCM(self.key).encrypt(nonce, data, model.encode()), nonce

    def _unpack(self, t: BiometricTemplate) -> list[float]:
        data = AESGCM(self.key).decrypt(t.nonce, t.ciphertext, (t.model_version or "").encode())
        return list(struct.unpack(f"<{len(data) // 4}f", data))

    def has_template(self, db: Session, user_id: uuid.UUID) -> bool:
        t = db.get(BiometricTemplate, user_id)
        return t is not None and t.ciphertext is not None

    def enroll(self, db: Session, user_id: uuid.UUID, embedding: Sequence[float], model: str) -> Enrollment:
        v = check_embedding(embedding)
        t = db.get(BiometricTemplate, user_id)
        if t is None:
            t = BiometricTemplate(user_id=user_id, enrollments=0)
            db.add(t)
        re = (t.enrollments or 0) > 0
        t.ciphertext, t.nonce = self._pack(v, model)
        t.model_version = model
        t.enrollments = (t.enrollments or 0) + 1
        t.enrolled_at, t.deleted_at = utcnow(), None
        db.flush()
        return Enrollment(re_enrolled=re)

    def verify(self, db: Session, user_id: uuid.UUID, embedding: Sequence[float], model: str) -> Verification:
        v = check_embedding(embedding)
        t = db.get(BiometricTemplate, user_id)
        if t is None or t.ciphertext is None:
            raise AppError(409, "no_template", "Эталон лица не создан")
        if (t.model_version or "") != model:
            # эмбеддинги разных моделей несравнимы: считаем несовпадением, а не ошибкой клиента
            return Verification(False, 0.0)
        s = similarity(self._unpack(t), v)
        return Verification(s >= self.threshold, round(s, 3))

    def delete(self, db: Session, user_id: uuid.UUID) -> bool:
        t = db.get(BiometricTemplate, user_id)
        if t is None or t.ciphertext is None:
            return False
        t.ciphertext = t.nonce = None
        t.deleted_at = utcnow()
        db.flush()
        return True


class EbsProvider:
    """Единая биометрическая система (Госуслуги Биометрия).

    Поток в production: кандидат подтверждает личность через ЕСИА и даёт согласие в ЕБС; при старте
    теста браузер передаёт кадр в SDK ЕБС (не на наш сервер), ЕБС возвращает подписанный результат
    аутентификации, который мы проверяем. Эталон у нас не хранится. Требует договора с оператором
    ЕБС и аккредитации — в демо не подключено.
    """

    name = "ebs"

    def _unavailable(self):
        raise AppError(503, "ebs_unavailable", "Проверка через ЕБС не подключена в этой среде")

    def has_template(self, db: Session, user_id: uuid.UUID) -> bool:
        self._unavailable()

    def enroll(self, db: Session, user_id: uuid.UUID, embedding: Sequence[float], model: str) -> Enrollment:
        self._unavailable()

    def verify(self, db: Session, user_id: uuid.UUID, embedding: Sequence[float], model: str) -> Verification:
        self._unavailable()

    def delete(self, db: Session, user_id: uuid.UUID) -> bool:
        return False  # эталон хранится в ЕБС; отзыв согласия — у оператора ЕБС


def get_provider(settings: Settings | None = None) -> BiometricProvider:
    settings = settings or get_settings()
    if settings.biometric_provider == "ebs":
        return EbsProvider()
    return LocalDemoProvider(settings)
