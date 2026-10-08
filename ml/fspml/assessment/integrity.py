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

**Окружение и полноэкранный режим** (все тесты на десктопе). Тест идёт в полноэкранном режиме:
время вне него на задании засчитывается как уход со страницы (по тому же правилу; уход на вкладку
и выход из полноэкранного режима не суммируются). Пометки без аннулирования: окно уменьшалось
внутри полноэкранного режима (например, открыты инструменты разработчика), подключён второй
монитор, видеоадаптер сеанса удалённого рабочего стола или виртуальной машины (имя рендерера
WebGL), браузер под управлением автоматизации (`navigator.webdriver`). Удалённый доступ через
TeamViewer/AnyDesk к физическому компьютеру браузер не видит — от него защищают проктор и формат
кейса с уточняющим вопросом; в production — экзаменационный браузер (Safe Exam Browser).

**Цифровой проктор** (по желанию кандидата, `ProctorSignals`). Детекторы работают в браузере, на
сервер приходят только счётчики по заданию и эмбеддинг лица для серверной сверки 1:1 с эталоном.
Правила консервативны — ложное срабатывание детектора не должно аннулировать честного кандидата:
* лица нет в кадре дольше `no_face_ms` — то же, что уход со страницы (общий счётчик уходов);
* телефон в кадре: на `phone_void_items` заданиях → `void`, реже → `review`;
* сверка с эталоном: сервер делит сверки на уверенное совпадение, серую зону и уверенное несовпадение.
  Один плохой кадр (поворот головы, наклон к листу, свет) — не сигнал: **эпизод** несовпадения —
  ≥ `mismatch_run` уверенно плохих сверок подряд (серая зона цепочку не рвёт и не продлевает).
  Несовпадение на старте или эпизод → `review`; вместе их ≥ `mismatch_void` или эпизод длиной
  ≥ `mismatch_long_run` → `void`;
* несколько лиц, речь на ≥ `speech_items` заданиях, взгляд вбок или вверх на ≥ `look_away_items` → `review`;
* взгляд вниз (лист бумаги, клавиатура) разрешён — только счётчик для работодателя;
* камера или микрофон отключены суммарно ≥ `lost_ms` — проктор прерван: бейдж снимается, тест идёт
  дальше как обычный (это не нарушение — у человека могла отвалиться камера).

**Тяжесть замечаний** (`severity`) — для доверия к результату в подборе: `hard` — прямые признаки
подмены или подсказки (несовпадение лица, телефон, посторонние в кадре на нескольких заданиях,
автоматизация браузера, удалённый рабочий стол или ВМ, вставка текста), `soft` — остальные замечания,
`none` — замечаний нет.
"""

from __future__ import annotations

import math
import re
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
    look_down_ms: int = 15_000  # взгляд вниз (лист) дольше — задание учитывается в счётчике, без пометки
    multi_face_hard_items: int = 2  # посторонние в кадре на стольких заданиях — тяжёлое замечание
    shrunk_ms: int = 2_000  # окно уменьшено дольше — пометка
    mismatch_run: int = 2  # уверенно плохих сверок подряд — эпизод несовпадения
    mismatch_long_run: int = 3  # эпизод такой длины — аннулирование
    mismatch_void: int = 2  # несовпадение на старте + эпизоды
    lost_ms: int = 30_000  # камера/микрофон отключены суммарно дольше — проктор прерван


DEFAULT_INTEGRITY = IntegrityConfig()


@dataclass(frozen=True)
class ItemSignals:
    focus_losses: int = 0
    away_ms: int = 0
    paste_attempts: int = 0
    copy_attempts: int = 0
    fullscreen_off_ms: int = 0  # вне полноэкранного режима (тест на десктопе)
    shrunk_ms: int = 0  # окно уменьшено внутри полноэкранного режима (инструменты разработчика)
    extended_screen: bool = False  # подключён второй монитор
    fullscreen_unavailable: bool = False  # браузер отказал в полноэкранном режиме

    @property
    def off_page_ms(self) -> int:
        """Время вне теста: уход на другую вкладку/окно или выход из полноэкранного режима (не сумма —
        переключение вкладки само выводит из полноэкранного режима)."""
        return max(self.away_ms if self.focus_losses > 0 else 0, self.fullscreen_off_ms)


_RDP = re.compile(r"remote display adapter|basic render driver|rdpdd|remotefx|citrix|vmware horizon", re.I)
_VM = re.compile(r"vmware|virtualbox|parallels|hyper-v|qemu|virgl|virtio|red hat|bochs", re.I)


def classify_renderer(renderer: str | None) -> Literal["rdp", "vm"] | None:
    """Видеоадаптер сеанса удалённого рабочего стола Windows или виртуальной машины (WebGL renderer).

    Программный рендеринг (SwiftShader, llvmpipe) не считается сигналом: он бывает и на обычных
    компьютерах с отключённым ускорением.
    """
    if not renderer:
        return None
    if _RDP.search(renderer):
        return "rdp"
    if _VM.search(renderer):
        return "vm"
    return None


@dataclass(frozen=True)
class EnvSignals:
    """Окружение на старте попытки."""

    virtual: Literal["rdp", "vm"] | None = None  # по имени видеоадаптера WebGL
    renderer: str | None = None
    webdriver: bool = False
    extended_screen: bool = False


@dataclass(frozen=True)
class ProctorSignals:
    """Счётчики проктора за задание; `checks` — серверные сверки эмбеддинга с эталоном, из них
    `mismatch` — уверенное несовпадение, `uncertain` — серая зона."""

    no_face_ms: int = 0
    multi_face_ms: int = 0
    phone_hits: int = 0
    look_away_ms: int = 0  # взгляд вбок или вверх
    look_down_ms: int = 0  # взгляд вниз: лист бумаги, клавиатура — разрешено
    speech_ms: int = 0
    cam_lost_ms: int = 0
    mic_lost_ms: int = 0
    mismatch: int = 0
    uncertain: int = 0
    checks: int = 0


@dataclass
class ProctoringReport:
    status: Literal["verified", "interrupted", "off"]
    identity: Literal["enrolled", "match", "uncertain", "mismatch"] | None = None
    reasons: list[str] = field(default_factory=list)
    phone_items: int = 0
    mismatches: int = 0  # уверенно плохие сверки (включая старт)
    episodes: int = 0  # эпизоды несовпадения (подряд идущие уверенно плохие сверки)
    uncertain: int = 0  # сверки в серой зоне — не сигнал
    checks: int = 0
    look_down_items: int = 0  # задания с долгим взглядом вниз — не сигнал
    severity: Literal["none", "soft", "hard"] = "none"
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
    severity: Literal["none", "soft", "hard"] = "none"

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


def _worse(a: str, b: str) -> Literal["none", "soft", "hard"]:
    order = ("none", "soft", "hard")
    return order[max(order.index(a), order.index(b))]  # type: ignore[return-value]


def mismatch_runs(proctor: Sequence[ProctorSignals], run: int) -> list[int]:
    """Длины эпизодов: подряд идущие уверенно плохие сверки (не короче `run`).

    Совпадение цепочку обрывает, серая зона — нет (и не продлевает): один кадр с наклонённой
    головой не делает из двух плохих кадров два отдельных случая и не создаёт новый.
    """
    out: list[int] = []
    cur = 0
    for s in proctor:
        good = s.checks - s.mismatch - s.uncertain
        if s.mismatch:
            cur += s.mismatch
        elif good > 0:
            if cur >= run:
                out.append(cur)
            cur = 0
    if cur >= run:
        out.append(cur)
    return out


def assess_proctor(
    proctor: Sequence[ProctorSignals],
    identity: Literal["enrolled", "match", "uncertain", "mismatch"] | None,
    config: IntegrityConfig = DEFAULT_INTEGRITY,
) -> tuple[ProctoringReport, bool]:
    """Отчёт проктора и признак аннулирования (без учёта уходов — они считаются в `assess`)."""
    reasons: list[str] = []
    severity: Literal["none", "soft", "hard"] = "none"
    phone = sum(1 for s in proctor if s.phone_hits > 0)
    runs = mismatch_runs(proctor, config.mismatch_run)
    start_bad = identity == "mismatch"
    mism = sum(s.mismatch for s in proctor) + (1 if start_bad else 0)
    uncertain = sum(s.uncertain for s in proctor) + (1 if identity == "uncertain" else 0)
    checks = sum(s.checks for s in proctor) + (1 if identity in ("match", "uncertain", "mismatch") else 0)
    if start_bad:
        reasons.append("на старте в кадре не владелец профиля: лицо не совпало с эталоном")
        severity = "hard"
    if runs:
        reasons.append(
            f"во время теста лицо не совпадало с эталоном профиля: {len(runs)} эпизод., "
            f"{sum(runs)} из {sum(s.checks for s in proctor)} сверок"
        )
        severity = "hard"
    if phone:
        reasons.append(f"в кадре телефон: {phone} задан.")
        severity = "hard"
    multi = sum(1 for s in proctor if s.multi_face_ms >= config.multi_face_ms)
    if multi:
        reasons.append(f"в кадре несколько человек: {multi} задан.")
        severity = _worse(severity, "hard" if multi >= config.multi_face_hard_items else "soft")
    speech = sum(1 for s in proctor if s.speech_ms >= config.speech_ms)
    if speech >= config.speech_items:
        reasons.append(f"речь во время заданий (возможно, задания зачитывались вслух): {speech} задан.")
        severity = _worse(severity, "soft")
    look = sum(1 for s in proctor if s.look_away_ms >= config.look_away_ms)
    if look >= config.look_away_items:
        reasons.append(f"взгляд надолго уходил в сторону от экрана: {look} задан.")
        severity = _worse(severity, "soft")
    look_down = sum(1 for s in proctor if s.look_down_ms >= config.look_down_ms)
    lost = sum(s.cam_lost_ms + s.mic_lost_ms for s in proctor)
    status: Literal["verified", "interrupted", "off"] = "verified"
    if lost >= config.lost_ms:
        status = "interrupted"
    void = (
        phone >= config.phone_void_items
        or len(runs) + (1 if start_bad else 0) >= config.mismatch_void
        or any(r >= config.mismatch_long_run for r in runs)
    )
    return (
        ProctoringReport(
            status,
            identity,
            reasons,
            phone_items=phone,
            mismatches=mism,
            episodes=len(runs),
            uncertain=uncertain,
            checks=checks,
            lost_ms=lost,
            look_down_items=look_down,
            severity=severity,
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
    identity: Literal["enrolled", "match", "uncertain", "mismatch"] | None = None,
    env: EnvSignals | None = None,
) -> IntegrityReport:
    """proctor=None — тест без проктора; иначе счётчики проктора по тем же заданиям, что и signals."""
    pr = list(proctor) if proctor is not None else None
    no_face = [(pr[i].no_face_ms if pr is not None and i < len(pr) else 0) for i in range(len(signals))]
    # лицо пропало из кадра надолго — то же, что уход со страницы
    gone = [nf >= config.no_face_ms for nf in no_face]
    off = [s.off_page_ms if s.off_page_ms >= config.min_away_ms else 0 for s in signals]
    left = [i for i in range(len(signals)) if off[i] or gone[i]]
    away = sum(off[i] + (no_face[i] if gone[i] else 0) for i in left)
    pastes = sum(s.paste_attempts for s in signals)
    copies = sum(s.copy_attempts for s in signals)
    lz = person_fit_lz(pairs, theta) if theta is not None and len(pairs) >= config.lz_min_items else None
    reasons: list[str] = []
    # тяжёлые замечания (прямые признаки подмены или подсказки); остальные — мягкие
    hard = False
    if left:
        where = ["со страницы теста"]
        if any(s.fullscreen_off_ms >= config.min_away_ms for s in signals):
            where.append("из полноэкранного режима")
        if any(gone):
            where.append("из кадра")
        what = "уходы " + (", ".join(where[:-1]) + " или " + where[-1] if len(where) > 1 else where[0])
        reasons.append(f"{what}: {len(left)} задан., суммарно {_minutes(away)}")
    shrunk = sum(1 for s in signals if s.shrunk_ms >= config.shrunk_ms)
    if shrunk:
        reasons.append(
            f"окно теста уменьшалось в полноэкранном режиме (например, открывались инструменты разработчика): {shrunk} задан."
        )
    if any(s.fullscreen_unavailable for s in signals):
        reasons.append("полноэкранный режим был недоступен в браузере кандидата")
    if (env and env.extended_screen) or any(s.extended_screen for s in signals):
        reasons.append("к компьютеру был подключён второй монитор")
    if env and env.virtual:
        where = "в сеансе удалённого рабочего стола" if env.virtual == "rdp" else "в виртуальной машине"
        reasons.append(f"тест проходил {where} (видеоадаптер «{env.renderer}»)")
        hard = True
    if env and env.webdriver:
        reasons.append("браузер был под управлением программы автоматизации (webdriver)")
        hard = True
    if pastes:
        reasons.append(f"попытки вставить текст в ответ: {pastes}")
        hard = True
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
    severity: Literal["none", "soft", "hard"] = "hard" if hard else ("soft" if reasons else "none")
    if proctoring is not None:
        severity = _worse(severity, proctoring.severity)
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
        severity=severity,
    )
