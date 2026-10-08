"""Надёжность прохождения теста: поведенческие сигналы браузера + статистика согласованности ответов.

Почему не «запрет и всё». Клиентские запреты (копирование, вставка) останавливают только
ленивое списывание: задание можно сфотографировать, а оверлей-подсказчик браузер не видит.
Поэтому решение принимается по **совокупности** признаков (как в Duolingo English Test:
поведенческие сигналы + статистика ответов + правило, понятное кандидату заранее):

* **Уход со страницы** — переключение вкладки или окна (`visibilitychange` + `blur`) с длительностью.
  Короткие (< `min_away_ms`) не считаются: случайный клик мимо окна не повод для подозрений.
* **Попытки копирования/вставки** — текст задания копировать нельзя, вставлять в ответ — тоже;
  сама попытка — сигнал.
* **Согласованность ответов (person-fit)** — стандартизованный индекс lz (Drasgow, Levine &
  Williams, 1985): насколько вероятна наблюдаемая последовательность верных/неверных ответов при
  оценённой способности θ. Сильно отрицательный lz — «неестественный» паттерн (верно на трудных,
  неверно на лёгких), типичный для частичной подсказки. Это мягкий сигнал: он не аннулирует
  результат сам по себе, а помечает его для работодателя.

Правило (известно кандидату до начала и показывается при каждом уходе):
* `void` — попытка аннулируется и засчитывается как неудачная, если уходов со страницы на
  разных заданиях ≥ `void_items`, или суммарно вне страницы ≥ `void_away_ms`, или попыток
  вставки ≥ `void_pastes`;
* `review` — результат засчитывается, но работодатель видит пометку, если были единичные уходы,
  попытки копирования/вставки или lz < `lz_threshold`;
* `clean` — замечаний нет.

**Цифровой проктор** (по желанию кандидата, `ProctorSignals`). Детекторы работают в браузере, на
сервер приходят только счётчики по заданию и эмбеддинг лица для серверной сверки 1:1 с эталоном.
Правила консервативны — ложное срабатывание детектора не должно аннулировать честного кандидата:
* лица нет в кадре дольше `no_face_ms` — то же, что уход со страницы (общий счётчик уходов);
* телефон в кадре: на `phone_void_items` заданиях → `void`, реже → `review`;
* сверка с эталоном не совпала: на старте или однажды за тест → `review`, ≥ `mismatch_void` раз → `void`;
* несколько лиц, речь на ≥ `speech_items` заданиях, взгляд в сторону на ≥ `look_away_items` → `review`;
* камера или микрофон отключены суммарно ≥ `lost_ms` — проктор прерван: бейдж снимается, тест идёт
  дальше как обычный (это не нарушение — у человека могла отвалиться камера).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal

from .irt import ItemParams, prob


@dataclass(frozen=True)
class IntegrityConfig:
    min_away_ms: int = 2000  # уход короче — не сигнал
    void_items: int = 3  # уходы на стольких разных заданиях → аннулирование
    void_away_ms: int = 60_000  # суммарно вне страницы
    void_pastes: int = 3
    lz_threshold: float = -2.0  # одностороннее p ≈ 0.023
    lz_min_items: int = 10
    # цифровой проктор
    no_face_ms: int = 20_000  # лица нет в кадре дольше — засчитывается как уход
    phone_void_items: int = 3
    multi_face_ms: int = 5_000
    speech_ms: int = 3_000  # речь на задании дольше — задание с речью
    speech_items: int = 2
    look_away_ms: int = 15_000
    look_away_items: int = 3
    mismatch_void: int = 2
    lost_ms: int = 30_000  # камера/микрофон отключены суммарно дольше — проктор прерван


DEFAULT_INTEGRITY = IntegrityConfig()


@dataclass(frozen=True)
class ItemSignals:
    focus_losses: int = 0
    away_ms: int = 0
    paste_attempts: int = 0
    copy_attempts: int = 0


@dataclass(frozen=True)
class ProctorSignals:
    """Счётчики проктора за задание; `mismatch`/`checks` — серверные сверки эмбеддинга с эталоном."""

    no_face_ms: int = 0
    multi_face_ms: int = 0
    phone_hits: int = 0
    look_away_ms: int = 0
    speech_ms: int = 0
    cam_lost_ms: int = 0
    mic_lost_ms: int = 0
    mismatch: int = 0
    checks: int = 0


@dataclass
class ProctoringReport:
    status: Literal["verified", "interrupted", "off"]
    identity: Literal["enrolled", "match", "mismatch"] | None = None
    reasons: list[str] = field(default_factory=list)
    phone_items: int = 0
    mismatches: int = 0
    checks: int = 0
    lost_ms: int = 0  # суммарно без камеры/микрофона; не нарушение, но снимает бейдж проктора

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IntegrityReport:
    level: Literal["clean", "review", "void"]
    items_left: int  # задания, во время которых кандидат уходил со страницы
    away_ms: int
    paste_attempts: int
    copy_attempts: int
    lz: float | None
    reasons: list[str] = field(default_factory=list)
    # сколько ещё уходов допустимо до аннулирования (для живого предупреждения)
    leaves_left: int = 0
    proctoring: ProctoringReport | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def person_fit_lz(pairs: Sequence[tuple[ItemParams, bool]], theta: float) -> float | None:
    """Стандартизованный индекс lz для дихотомических ответов при способности θ."""
    if not pairs:
        return None
    l0 = e = v = 0.0
    for params, correct in pairs:
        p = float(min(max(prob(theta, params.a, params.b, params.c), 1e-6), 1 - 1e-6))
        q = 1.0 - p
        l0 += math.log(p) if correct else math.log(q)
        e += p * math.log(p) + q * math.log(q)
        v += p * q * math.log(p / q) ** 2
    if v <= 1e-9:
        return None
    return (l0 - e) / math.sqrt(v)


def _minutes(ms: int) -> str:
    s = round(ms / 1000)
    return f"{s // 60} мин {s % 60} с" if s >= 60 else f"{s} с"


def assess_proctor(
    proctor: Sequence[ProctorSignals],
    identity: Literal["enrolled", "match", "mismatch"] | None,
    config: IntegrityConfig = DEFAULT_INTEGRITY,
) -> tuple[ProctoringReport, bool]:
    """Отчёт проктора и признак аннулирования (без учёта уходов — они считаются в `assess`)."""
    reasons: list[str] = []
    phone = sum(1 for s in proctor if s.phone_hits > 0)
    mism = sum(s.mismatch for s in proctor) + (1 if identity == "mismatch" else 0)
    checks = sum(s.checks for s in proctor) + (1 if identity in ("match", "mismatch") else 0)
    if identity == "mismatch":
        reasons.append("на старте в кадре не владелец профиля: лицо не совпало с эталоном")
    in_test = sum(s.mismatch for s in proctor)
    if in_test:
        reasons.append(
            f"во время теста лицо не совпало с эталоном профиля: {in_test} из {sum(s.checks for s in proctor)} сверок"
        )
    if phone:
        reasons.append(f"в кадре телефон: {phone} задан.")
    multi = sum(1 for s in proctor if s.multi_face_ms >= config.multi_face_ms)
    if multi:
        reasons.append(f"в кадре несколько человек: {multi} задан.")
    speech = sum(1 for s in proctor if s.speech_ms >= config.speech_ms)
    if speech >= config.speech_items:
        reasons.append(f"речь во время заданий (возможно, задания зачитывались вслух): {speech} задан.")
    look = sum(1 for s in proctor if s.look_away_ms >= config.look_away_ms)
    if look >= config.look_away_items:
        reasons.append(f"взгляд надолго уходил в сторону от экрана: {look} задан.")
    lost = sum(s.cam_lost_ms + s.mic_lost_ms for s in proctor)
    status: Literal["verified", "interrupted", "off"] = "verified"
    if lost >= config.lost_ms:
        status = "interrupted"
    void = phone >= config.phone_void_items or mism >= config.mismatch_void
    return (
        ProctoringReport(
            status, identity, reasons, phone_items=phone, mismatches=mism, checks=checks, lost_ms=lost
        ),
        void,
    )


def assess(
    signals: Sequence[ItemSignals],
    *,
    pairs: Sequence[tuple[ItemParams, bool]] = (),
    theta: float | None = None,
    config: IntegrityConfig = DEFAULT_INTEGRITY,
    proctor: Sequence[ProctorSignals] | None = None,
    identity: Literal["enrolled", "match", "mismatch"] | None = None,
) -> IntegrityReport:
    """proctor=None — тест без проктора; иначе счётчики проктора по тем же заданиям, что и signals."""
    pr = list(proctor) if proctor is not None else None
    no_face = [(pr[i].no_face_ms if pr is not None and i < len(pr) else 0) for i in range(len(signals))]
    # лицо пропало из кадра надолго — то же, что уход со страницы
    gone = [nf >= config.no_face_ms for nf in no_face]
    left = [
        i
        for i, s in enumerate(signals)
        if (s.focus_losses > 0 and s.away_ms >= config.min_away_ms) or gone[i]
    ]
    away = sum(
        (signals[i].away_ms if signals[i].focus_losses > 0 else 0) + (no_face[i] if gone[i] else 0)
        for i in left
    )
    pastes = sum(s.paste_attempts for s in signals)
    copies = sum(s.copy_attempts for s in signals)
    lz = person_fit_lz(pairs, theta) if theta is not None and len(pairs) >= config.lz_min_items else None
    reasons: list[str] = []
    if left:
        what = "уходы со страницы теста или из кадра" if any(gone) else "уходы со страницы теста"
        reasons.append(f"{what}: {len(left)} задан., суммарно {_minutes(away)}")
    if pastes:
        reasons.append(f"попытки вставить текст в ответ: {pastes}")
    if copies:
        reasons.append(f"попытки скопировать текст задания: {copies}")
    void = len(left) >= config.void_items or away >= config.void_away_ms or pastes >= config.void_pastes
    proctoring = None
    if pr is not None:
        proctoring, p_void = assess_proctor(pr, identity, config)
        reasons += proctoring.reasons
        void = void or p_void
    if lz is not None and lz < config.lz_threshold:
        reasons.append(
            f"непоследовательный паттерн ответов (индекс согласованности lz = {lz:+.1f}): "
            "верные ответы на трудных заданиях при ошибках на лёгких"
        )
    level: Literal["clean", "review", "void"] = "void" if void else ("review" if reasons else "clean")
    return IntegrityReport(
        level=level,
        items_left=len(left),
        away_ms=away,
        paste_attempts=pastes,
        copy_attempts=copies,
        lz=None if lz is None else round(lz, 2),
        reasons=reasons,
        leaves_left=max(0, config.void_items - len(left)),
        proctoring=proctoring,
    )
