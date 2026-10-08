from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base, new_id, utcnow


class Attempt(Base):
    """Попытка тестирования на заявленный грейд."""

    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.user_id", ondelete="CASCADE"), index=True
    )
    specialization: Mapped[str] = mapped_column(String(32))
    grade: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))  # initial | upgrade | downgrade | refresh
    status: Mapped[str] = mapped_column(
        String(16), default="in_progress", index=True
    )  # in_progress | passed | failed | abandoned | voided (аннулирована: нарушение правил прохождения)
    blueprint: Mapped[dict] = mapped_column(default=dict)
    stack: Mapped[list] = mapped_column(default=list)
    # семейства заданий, которые кандидат видел в прошлых попытках: выбираются в последнюю очередь
    seen_families: Mapped[list] = mapped_column(default=list)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    result: Mapped[dict | None] = mapped_column(default=None)
    # цифровой проктор (по желанию кандидата) и сверка с эталоном лица на старте:
    # {status: enrolled | match | mismatch, similarity, re_enrolled, provider}
    proctored: Mapped[bool] = mapped_column(default=False)
    identity: Mapped[dict | None] = mapped_column(default=None)
    # окружение на старте: {renderer, virtual, webdriver, extended_screen, desktop, fullscreen}
    env: Mapped[dict | None] = mapped_column(default=None)


class AttemptItem(Base):
    """Выданное задание. Текст не хранится: экземпляр восстанавливается по HMAC-seed (attempt, position)."""

    __tablename__ = "attempt_items"
    __table_args__ = (UniqueConstraint("attempt_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int]
    # item — задание теста знаний; scenario — практический кейс; probe — уточняющий вопрос по кейсу
    kind: Mapped[str] = mapped_column(String(16), default="item")
    family_id: Mapped[str] = mapped_column(String(64), index=True)
    skill: Mapped[str] = mapped_column(String(32))
    issued_at: Mapped[datetime] = mapped_column(default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(default=None)
    response: Mapped[dict | None] = mapped_column(default=None)  # {"value": ...}
    correct: Mapped[bool | None] = mapped_column(default=None)
    time_ms: Mapped[int | None] = mapped_column(default=None)
    tab_switches: Mapped[int] = mapped_column(default=0)  # уходы со страницы (вкладка/окно) ≥ 1,5 с
    away_ms: Mapped[int] = mapped_column(default=0)
    paste_attempts: Mapped[int] = mapped_column(default=0)
    copy_attempts: Mapped[int] = mapped_column(default=0)
    meta: Mapped[dict | None] = mapped_column(default=None)  # кейс: {scenario, probe, grading}
    # счётчики проктора за задание (без изображений и эмбеддингов) + результат серверной сверки
    proctor: Mapped[dict | None] = mapped_column(default=None)
    # полноэкранный режим и экран за задание: {fullscreen_off_ms, fullscreen_exits, shrunk_ms, extended_screen}
    client: Mapped[dict | None] = mapped_column(default=None)
    score: Mapped[float | None] = mapped_column(default=None)  # кейс/вопрос: оценка 0..1
    expected_p: Mapped[float | None] = mapped_column(
        default=None
    )  # P(верно | θ̂ до ответа) — для мониторинга утечек


class FamilyStats(Base):
    """Состояние семейства в продакшене: перекалиброванные параметры, CUSUM, вывод из ротации."""

    __tablename__ = "family_stats"

    family_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    n_responses: Mapped[int] = mapped_column(default=0)
    n_correct: Mapped[int] = mapped_column(default=0)
    cusum: Mapped[float] = mapped_column(default=0.0)
    flagged_at: Mapped[datetime | None] = mapped_column(default=None)
    disabled: Mapped[bool] = mapped_column(default=False)
    a: Mapped[float | None] = mapped_column(default=None)
    b: Mapped[float | None] = mapped_column(default=None)
    calibrated_at: Mapped[datetime | None] = mapped_column(default=None)
