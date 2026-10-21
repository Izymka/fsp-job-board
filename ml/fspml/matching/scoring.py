"""Механика подбора: сила профиля внутри категории и соответствие потребности работодателя.

Два скора — ровно по ТЗ:

* `profile_strength` — порядок *внутри категории* (специализация × грейд): результат теста,
  подтверждённые достижения ФСП и регулярные задания. Не зависит от работодателя.
* `match_score` — выдача *под потребность*: соответствие требуемым навыкам (подтверждённое
  тестом весит больше заявленного), сила профиля, совместимость условий (вилка, формат,
  отрасль — прокси готовности принять приглашение) и свежесть профиля.

Каждый скор раскладывается на вклады компонентов — из них строится объяснение выдачи.
Веса вынесены в `Weights` и обоснованы в docs/matching.md; чувствительность к ним проверяется
в `fspml.validation.matching`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np

from ..catalog import Catalog, get_catalog
from ..nlp.skills import get_dictionary
from .experience import effective_years, years_from, years_ru

# --------------------------------------------------------------------------------------- данные


@dataclass(frozen=True)
class FspAchievement:
    discipline: str
    level: str
    result: str
    event_date: date
    title: str = ""
    role: str | None = None


@dataclass
class CandidateFeatures:
    id: str
    specialization: str
    grade: str | None  # подтверждённый тестом грейд; None — категория не присвоена
    theta: float | None = None
    theta_se: float | None = None
    skill_status: dict[str, str] = field(
        default_factory=dict
    )  # навык теста → confirmed/uncertain/weak/no_data
    skill_theta: dict[str, tuple[float, float]] = field(default_factory=dict)  # навык → (θ, SE) из теста
    claimed: set[str] = field(default_factory=set)  # технологии из профиля/опроса/резюме
    task_skills: dict[str, float] = field(default_factory=dict)  # навык → 0..1 по регулярным заданиям
    tasks_score: float = 0.0  # 0..1, с затуханием по времени
    fsp: list[FspAchievement] | None = None  # None — ФСП ID не привязан
    salary_from: int | None = None
    salary_to: int | None = None
    work_formats: set[str] = field(default_factory=set)
    industries: set[str] = field(default_factory=set)  # предпочтительные отрасли
    excluded_industries: set[str] = field(default_factory=set)
    excluded_companies: set[str] = field(default_factory=set)
    search_status: str = "open"
    last_active: date | None = None
    tested_at: date | None = None
    about: str = ""
    embedding: np.ndarray | None = None
    proctored: bool = False  # грейд подтверждён тестом с цифровым проктором без перерывов
    integrity: str = "ok"  # уровень надёжности попытки, подтвердившей грейд: ok / clean / review
    integrity_severity: str | None = None  # none / soft / hard; None — нет данных (выводится из integrity)
    experience_years: float | None = None  # общий стаж (из опроса или резюме), не проверяется
    relevant_years: float | None = None  # стаж в той же специализации; None — нет разбивки по местам работы
    it_years: float | None = None  # стаж в IT (любая специализация)
    industry_years: dict[str, float] = field(default_factory=dict)  # отрасль → годы


# Доверие к подтверждённому грейду — множитель итогового скора. Главное — был ли проктор: результат
# без наблюдения легко списать, поэтому тест с проктором даже с тяжёлыми замечаниями весит больше,
# чем чистый тест без проктора. Прерванный проктор (камера отключалась) — как без проктора: иначе
# выгодно включить проктор и выключить камеру. Внутри яруса — по тяжести замечаний
# (`fspml.assessment.integrity`: hard — признаки подмены или подсказки, soft — остальные).
TRUST = {
    "proctor_clean": 1.0,
    "proctor_soft": 0.9,
    "proctor_hard": 0.8,
    "plain_clean": 0.6,
    "plain_review": 0.5,
}
TRUST_REASON = {
    "proctor_clean": ("positive", "Тест пройден с цифровым проктором"),
    "proctor_soft": ("positive", "Тест с цифровым проктором, есть незначительные замечания"),
    "proctor_hard": ("neutral", "Тест с цифровым проктором, есть замечания о самостоятельности"),
    "plain_clean": ("neutral", "Тест без проктора: результат не подтверждён наблюдением"),
    "plain_review": ("negative", "Тест без проктора, есть замечания о самостоятельности"),
}

# Опыт работы — множитель относительно требования вакансии (если не указано — типичного для грейда).
# Засчитывается релевантный опыт (та же специализация) и 30% прочего IT-опыта. Нехватка опыта
# штрафуется заметно: без опыта при требовании «от N лет» множитель 0.5 — так рассуждает работодатель.
# Превышение даёт небольшой плюс (стаж заявлен кандидатом, а грейд проверен тестом).
GRADE_MIN_YEARS = {"intern": 0.0, "junior": 0.5, "middle": 2.0, "senior": 4.0, "lead": 6.0}
EXP_SHORT_SLOPE, EXP_FLOOR = 0.5, 0.5
EXP_ABOVE_STEP, EXP_MAX = 0.015, 1.06
EXP_UNKNOWN = 0.9  # опыт не указан, а вакансия его требует
EXP_INDUSTRY = 1.04  # от года опыта в отрасли вакансии
# v7: подтверждённые реестром достижения ФСП — практический опыт командной разработки в сжатые сроки.
# Сила ФСП (0..1, `fsp_strength`) засчитывается как до FSP_YEARS_MAX лет релевантного опыта и закрывает
# только нехватку стажа: свежий призёр всероссийских соревнований (сила ≈ 0.5) закрывает требование
# Junior (полгода), частично — Middle, на Senior почти не влияет. Так молодой участник ФСП без
# коммерческого стажа не теряет половину скора только из-за пустой строки «место работы» в резюме.
FSP_YEARS_MAX = 1.0


def trust_level(c: CandidateFeatures) -> str | None:
    """Ярус доверия (ключ `TRUST`); None — грейд не подтверждён тестом (множитель не применяется)."""
    if c.theta is None or c.grade is None:
        return None
    sev = c.integrity_severity or ("soft" if c.integrity == "review" else "none")
    if c.proctored:
        return {"none": "proctor_clean", "soft": "proctor_soft"}.get(sev, "proctor_hard")
    return "plain_clean" if sev == "none" else "plain_review"


def required_years(need: Need) -> tuple[float, bool]:
    """Требуемый опыт и признак, что он указан в вакансии (а не взят по грейду)."""
    if need.min_years is not None:
        return need.min_years, True
    return GRADE_MIN_YEARS.get(need.grade, 0.0), False


def experience_fit(c: CandidateFeatures, need: Need, fsp: float = 0.0) -> tuple[float, list[Reason]]:
    """fsp — сила достижений ФСП (v7): засчитывается как опыт, если вакансия его требует.
    У вакансии «открыта для ФСП» потолок — требуемый стаж, а не FSP_YEARS_MAX."""
    req, explicit = required_years(need)
    cap = max(FSP_YEARS_MAX, req) if need.fsp_friendly else FSP_YEARS_MAX
    fsp_years = cap * min(max(fsp, 0.0), 1.0) if req > 0 else 0.0
    req_t = (
        f"требуется {years_from(req)}"
        if explicit
        else f"для {need.grade.capitalize()} обычно {years_from(req)}"
    )
    if c.relevant_years is None and c.experience_years is None:
        if fsp_years <= 0:
            return (EXP_UNKNOWN if req > 0 else 1.0), [Reason("neutral", "Опыт работы не указан")]
        f = max(EXP_UNKNOWN, _short_fit(fsp_years, req))
        return f, [Reason("neutral", "Опыт работы не указан"), _fsp_experience_reason(min(fsp_years, req))]
    rel = c.relevant_years if c.relevant_years is not None else c.experience_years or 0.0
    it = c.it_years if c.it_years is not None else rel
    eff = effective_years(rel, it)
    # ФСП закрывает только нехватку стажа: сверх требования бонус даёт лишь реальный опыт
    fsp_counted = min(fsp_years, req - eff) if fsp_years > 0 and eff < req else 0.0
    eff += fsp_counted
    if req <= 0:
        f = 1 + min(0.04, 0.02 * eff)
    elif eff >= req:
        f = 1 + min(EXP_MAX - 1, EXP_ABOVE_STEP * (eff - req))
    else:
        f = _short_fit(eff, req)
    reasons = []
    if it <= 0 and (c.experience_years or 0) <= 0:
        text, kind = "Нет коммерческого опыта", "negative" if req > 0 else "neutral"
    elif rel <= 0:
        text, kind = f"Нет опыта в этой роли (в IT — {years_ru(it)})", "negative" if req > 0 else "neutral"
    else:
        text = f"Релевантный опыт: {years_ru(rel)}"
        if it > rel + 0.4:
            text += f" (всего в IT — {years_ru(it)})"
        kind = "positive" if eff - fsp_counted >= req else "negative"
    if req > 0:
        text += f"; {req_t}"
    if fsp_counted and kind == "negative" and eff >= req:
        kind = "neutral"  # нехватку стажа закрыли достижения ФСП
    reasons.append(Reason(kind, text))
    if fsp_counted:
        reasons.append(_fsp_experience_reason(fsp_counted))
    if need.industry and c.industry_years.get(need.industry, 0.0) >= 1.0:
        f *= EXP_INDUSTRY
        reasons.append(
            Reason("positive", f"Опыт в отрасли вакансии: {years_ru(c.industry_years[need.industry])}")
        )
    return f, reasons


def _short_fit(eff: float, req: float) -> float:
    if eff >= req:
        return 1.0
    return max(EXP_FLOOR, 1 - EXP_SHORT_SLOPE * (req - eff) / req)


def _fsp_experience_reason(years: float) -> Reason:
    months = max(1, round(years * 12))
    return Reason("positive", f"Достижения ФСП засчитаны как практический опыт (≈ {months} мес.)")


@dataclass
class Need:
    specialization: str
    grade: str
    skills: dict[str, float] = field(default_factory=dict)  # технология → важность 0..1
    salary_from: int | None = None
    salary_to: int | None = None
    work_format: str | None = None
    industry: str | None = None
    company_id: str | None = None
    text: str = ""
    embedding: np.ndarray | None = None
    include_adjacent: bool = True
    min_years: float | None = None  # требуемый опыт из вакансии; None — типичный для грейда
    # «Открыта для участников ФСП»: работодатель засчитывает достижения ФСП как опыт целиком —
    # потолок ФСП-опыта поднимается с FSP_YEARS_MAX до требования вакансии (только v7)
    fsp_friendly: bool = False


@dataclass(frozen=True)
class Weights:
    # profile_strength
    ps_test: float = 0.60
    ps_fsp: float = 0.25
    ps_tasks: float = 0.15
    # match_score
    need_fit: float = 0.40
    profile: float = 0.30
    conditions: float = 0.20
    freshness: float = 0.10
    adjacent_grade_multiplier: float = 0.85
    # need_fit
    coverage_share: float = 0.75
    claim_base: float = 0.4  # заявленная технология без подтверждения
    unclaimed_factor: float = 0.25  # навык подтверждён тестом, но технология не заявлена
    # conditions
    cond_salary: float = 0.6
    cond_format: float = 0.3
    cond_industry: float = 0.1
    freshness_days: float = 60.0


DEFAULT_WEIGHTS = Weights()
# v7: ФСП — весомая часть силы профиля. Доля ФСП в итоговом скоре: 0.30 · 0.25 = 7.5% (v5) →
# 0.35 · 0.40 = 14% (v7); веса выбраны перебором (docs/matching.md), ограничение — NDCG@10 падает
# не больше чем на 0.01 на синтетической валидации и бенчмарке со слепой разметкой.
WEIGHTS_V7 = replace(DEFAULT_WEIGHTS, ps_test=0.45, ps_fsp=0.40, ps_tasks=0.15, need_fit=0.35, profile=0.35)


def weights_for(version: int) -> Weights:
    """Веса силы профиля и выдачи для версии формулы (`rank(version=...)`)."""
    return WEIGHTS_V7 if version >= 7 else DEFAULT_WEIGHTS


# Сила подтверждения навыка тестом. «Нет данных» — нейтрально, «слабо» — хуже, чем нет данных:
# тест опроверг заявленное.
STATUS_EVIDENCE = {"confirmed": 1.0, "uncertain": 0.6, "no_data": 0.35, "weak": 0.0}


@dataclass
class Reason:
    kind: str  # positive / neutral / negative
    text: str


@dataclass
class Scored:
    candidate_id: str
    score: float
    profile_strength: float
    components: dict[str, float]  # вклад в итоговый скор
    details: dict[str, float]  # значения компонентов 0..1
    reasons: list[Reason]
    missing: list[str]
    adjacent: bool
    salary_fit: str  # within / partial / below / above / unknown


# ----------------------------------------------------------------------------------- компоненты


def fsp_strength(
    achievements: Sequence[FspAchievement] | None, spec: str, today: date, catalog: Catalog | None = None
) -> float:
    """Noisy-OR по достижениям: насыщается, десять участий не равны победе."""
    if not achievements:
        return 0.0
    catalog = catalog or get_catalog()
    hl = float(catalog.fsp["half_life_years"])
    prod = 1.0
    for a in achievements:
        age = max(0.0, (today - a.event_date).days / 365.25)
        s = (
            catalog.fsp_weight("levels", a.level)
            * catalog.fsp_weight("results", a.result)
            * catalog.fsp_relevance(a.discipline, spec)
            * 0.5 ** (age / hl)
        )
        prod *= 1.0 - min(max(s, 0.0), 0.99)
    return 1.0 - prod


def test_strength(c: CandidateFeatures, catalog: Catalog | None = None) -> float:
    """Насколько уверенно θ превышает порог подтверждённого грейда (0..1), со штрафом за неточность."""
    if c.theta is None or c.grade is None:
        return 0.0
    catalog = catalog or get_catalog()
    cut = catalog.grade(c.grade).cut
    z = (c.theta - cut) / 0.8
    base = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    penalty = min(0.15, max(0.0, (c.theta_se or 0.0) - 0.35) * 0.5)
    return max(0.0, base - penalty)


def profile_strength(
    c: CandidateFeatures, today: date, w: Weights = DEFAULT_WEIGHTS, catalog: Catalog | None = None
) -> tuple[float, dict]:
    t = test_strength(c, catalog)
    f = fsp_strength(c.fsp, c.specialization, today, catalog)
    k = c.tasks_score
    total = w.ps_test * t + w.ps_fsp * f + w.ps_tasks * k
    return total, {"test": t, "fsp": f, "tasks": k}


def _skill_proof(c: CandidateFeatures, skill: str, cut: float | None) -> tuple[float, bool]:
    """Подтверждённость навыка тестом: P(θ_навыка > порог грейда потребности), если есть оценка."""
    if cut is not None and skill in c.skill_theta:
        th, se = c.skill_theta[skill]
        return 0.5 * (1 + math.erf((th - cut) / (max(se, 0.2) * math.sqrt(2)))), True
    status = c.skill_status.get(skill, "no_data")
    return STATUS_EVIDENCE.get(status, 0.35), status != "no_data"


def skill_evidence(
    c: CandidateFeatures, tech: str, w: Weights = DEFAULT_WEIGHTS, cut: float | None = None
) -> tuple[float, str]:
    """Подтверждённость технологии у кандидата: 0..1 и источник (test / tasks / claim / none).

    Тест подтверждает *заявление*, а не заменяет его: заявленная технология с подтверждённым
    тестом навыком = 1.0; заявленная без данных теста ≈ 0.6; заявленная, но опровергнутая тестом
    = 0.4; не заявленная при сильном навыке — лишь общий потенциал (≤ 0.25).
    """
    dic = get_dictionary()
    t = dic.techs.get(tech)
    assess = t.assess if t else ()
    claimed = tech in c.claimed
    if not assess:
        # технология не проверяется тестом (например, Java): доверяем заявлению с понижением
        return (0.6 if claimed else 0.0), ("claim" if claimed else "none")
    proofs = [_skill_proof(c, a, cut) for a in assess]
    test_ev = max(p for p, _ in proofs)
    has_test = any(h for _, h in proofs)
    task_ev = max(c.task_skills.get(a, 0.0) for a in assess)
    proof = max(test_ev, task_ev)
    if claimed:
        value = w.claim_base + (1 - w.claim_base) * proof
    else:
        value = w.unclaimed_factor * (proof if has_test or task_ev > 0 else 0.0)
    if task_ev > test_ev and task_ev > 0:
        src = "tasks"
    elif has_test and test_ev >= 0.6:
        src = "test"
    else:
        src = "claim" if claimed else "none"
    return value, src


def salary_fit(c: CandidateFeatures, offer_from: int | None, offer_to: int | None) -> tuple[float, str]:
    """Совместимость вилки работодателя с ожиданиями кандидата (без раскрытия чисел)."""
    if c.salary_from is None or (offer_from is None and offer_to is None):
        return 0.7, "unknown"
    top = offer_to or offer_from
    if top >= c.salary_from:
        if c.salary_to is not None and offer_from is not None and offer_from > c.salary_to:
            return 1.0, "above"
        if offer_from is not None and offer_from >= c.salary_from:
            return 1.0, "within"
        return 0.85, "partial"
    gap = (c.salary_from - top) / c.salary_from
    return max(0.0, 1.0 - 4 * gap), "below"


def format_fit(c: CandidateFeatures, fmt: str | None) -> float:
    if not fmt or not c.work_formats:
        return 0.8
    if fmt in c.work_formats:
        return 1.0
    if fmt == "hybrid" or "hybrid" in c.work_formats:
        return 0.5
    return 0.1


def freshness(c: CandidateFeatures, today: date, w: Weights = DEFAULT_WEIGHTS) -> float:
    dates = [d for d in (c.last_active, c.tested_at) if d]
    if not dates:
        return 0.3
    days = (today - max(dates)).days
    return math.exp(-max(0, days) / w.freshness_days)


# ----------------------------------------------------------------------------------- выдача


def eligible(c: CandidateFeatures, need: Need, catalog: Catalog) -> tuple[bool, bool]:
    """(попадает в выдачу, соседняя категория). Жёсткие правила видимости — здесь."""
    if c.grade is None or c.specialization != need.specialization:
        return False, False
    if c.search_status == "closed":
        return False, False
    if need.industry and need.industry in c.excluded_industries:
        return False, False
    if need.company_id and need.company_id in c.excluded_companies:
        return False, False
    diff = abs(catalog.grade_index(c.grade) - catalog.grade_index(need.grade))
    if diff == 0:
        return True, False
    if diff == 1 and need.include_adjacent:
        return True, True
    return False, False


def specificity(candidates: Sequence[CandidateFeatures], techs: Iterable[str]) -> dict[str, float]:
    """Специфичность требования внутри пула: √(−log доли кандидатов, заявивших технологию),
    со сглаживанием Лапласа — как IDF в информационном поиске.

    Git, Docker, REST есть почти у всех в категории (вес ≈ 0.8): они не отличают кандидатов.
    Go, PHP, Vue, Appium определяют стек вакансии (вес 1.3–1.6). Без этого Java-разработчик
    с Docker, Git и PostgreSQL закрывает Go-вакансию почти так же, как Go-разработчик.
    Корень смягчает перевес редких, но второстепенных меток («Интеграции»); выигрыш на
    бенчмарках устойчив к форме веса (ln, √, с потолком) — см. docs/bench.md.
    """
    pool = list(candidates)
    n = len(pool)
    return {t: math.sqrt(-math.log((sum(t in c.claimed for c in pool) + 1) / (n + 2))) for t in techs}


# Технологии, определяющие стек вакансии: языки и основные фреймворки. SQL и Bash есть почти
# в любом стеке, инфраструктура и библиотеки (Docker, Kafka, Figma) стек не определяют.
CORE_STACK = frozenset(
    {
        *"Python JavaScript TypeScript Java Kotlin Swift Objective-C Go C# C++ C Rust PHP Ruby".split(),
        *"Scala Dart R 1C Django FastAPI Flask Spring Node.js NestJS Laravel Gin React".split(),
        *"Next.js Vue Angular Svelte Android iOS Flutter".split(),
        "React Native",
        "Jetpack Compose",
    }
)


def core_stack(need: Need) -> tuple[str, ...]:
    """Основной стек вакансии (v6): обязательные языки и фреймворки — Go, PHP+Laravel, Vue.
    Пусто — у вакансии нет основного языка (аналитик, QA, DevOps), «ворота» не действуют."""
    return tuple(
        sorted(
            t
            for t, imp in need.skills.items()
            if imp >= DEFAULT_WEIGHTS_V2.must_importance and t in CORE_STACK
        )
    )


def score_candidate(
    c: CandidateFeatures,
    need: Need,
    today: date,
    *,
    w: Weights = DEFAULT_WEIGHTS,
    adjacent: bool = False,
    catalog: Catalog | None = None,
    percentile: float | None = None,
    spec_weights: Mapping[str, float] | None = None,
    gates: WeightsV2 | None = None,
    core: Sequence[str] = (),
    fsp_experience: bool = False,
) -> Scored:
    """spec_weights — специфичность требований (`specificity`), None — все равны (v1).
    gates — «ворота» v5: обязательные навыки, формат и вилка как множители; None — без ворот (v1).
    core — основной стек вакансии (`core_stack`, v6): нет ни одной его технологии — жёсткий множитель.
    fsp_experience — достижения ФСП засчитываются как опыт работы (v7, `experience_fit`)."""
    catalog = catalog or get_catalog()
    ps, ps_parts = profile_strength(c, today, w, catalog)
    spec_weights = spec_weights or {}

    # need_fit: покрытие требуемых технологий с учётом подтверждённости + семантика текста
    reasons: list[Reason] = []
    missing: list[str] = []
    confirmed_names, claimed_names = [], []
    must_num = must_den = 0.0
    if need.skills:
        num = den = 0.0
        need_cut = catalog.grade(need.grade).cut
        for tech, imp in need.skills.items():
            ev, src = skill_evidence(c, tech, w, cut=need_cut)
            wt = imp * spec_weights.get(tech, 1.0)
            num += wt * ev
            den += wt
            if imp >= DEFAULT_WEIGHTS_V2.must_importance:
                must_num += wt * ev
                must_den += wt
            if ev >= 0.85 and src in ("test", "tasks"):
                confirmed_names.append(tech)
            elif tech in c.claimed:
                claimed_names.append(tech)
            if ev < 0.5 and imp >= 0.6:
                missing.append(tech)
        coverage = num / den if den else 0.0
        # самые специфичные (определяющие стек) пробелы — первыми
        missing.sort(key=lambda t: -spec_weights.get(t, 1.0))
    else:
        coverage = 0.5
    must_cov = must_num / must_den if must_den else coverage
    semantic = None
    if need.embedding is not None and c.embedding is not None:
        cos = float(np.dot(need.embedding, c.embedding))
        semantic = min(1.0, max(0.0, (cos - 0.15) / 0.6))
    need_fit = (
        coverage if semantic is None else w.coverage_share * coverage + (1 - w.coverage_share) * semantic
    )

    sal, sal_kind = salary_fit(c, need.salary_from, need.salary_to)
    fmt = format_fit(c, need.work_format)
    ind = 1.0 if (not c.industries or (need.industry and need.industry in c.industries)) else 0.8
    conditions = w.cond_salary * sal + w.cond_format * fmt + w.cond_industry * ind
    fresh = freshness(c, today, w)

    raw = {
        "need_fit": w.need_fit * need_fit,
        "profile": w.profile * ps,
        "conditions": w.conditions * conditions,
        "freshness": w.freshness * fresh,
    }
    mult = w.adjacent_grade_multiplier if adjacent else 1.0
    gate = {}
    if gates is not None:
        # Решение рекрутера устроено как «И»: один жёсткий провал (нет обязательного языка,
        # офис против удалёнки, ожидания сильно выше вилки) не перекрывается достоинствами.
        gate = {
            "must": 1.0 if must_cov >= gates.gate_must_threshold else 0.5 + must_cov,
            "format": 1.0
            if fmt >= 0.8
            else (gates.gate_format_soft if fmt >= 0.5 else gates.gate_format_hard),
            "salary": _gate_salary(c, need, gates),
        }
        if core:
            # основной стек не заменяется смежным: C#-джун без Java не подходит Java-вакансии,
            # даже если тест, вилка и формат у него лучше, чем у Java-джуна
            cut = catalog.grade(need.grade).cut
            has = any(t in c.claimed or skill_evidence(c, t, w, cut=cut)[0] >= 0.5 for t in core)
            gate["core"] = 1.0 if has else gates.gate_core
        mult *= math.prod(gate.values())
        # доверие к грейду и стаж — тоже множители: кандидат с проктором выше при сопоставимом
        # соответствии, но заметно лучше подходящий без проктора его обгоняет
        trust = trust_level(c)
        gate["trust"] = TRUST[trust] if trust else 1.0
        gate["experience"], exp_reasons = experience_fit(
            c, need, fsp=ps_parts["fsp"] if fsp_experience else 0.0
        )
        mult *= gate["trust"] * gate["experience"]
    else:
        exp_reasons = []
    total = sum(raw.values()) * mult
    components = {k: v * mult for k, v in raw.items()}

    # --- объяснение ---
    if confirmed_names:
        reasons.append(Reason("positive", "Подтверждено тестом: " + ", ".join(confirmed_names[:5])))
    if claimed_names:
        reasons.append(Reason("neutral", "Заявлено, но не проверено: " + ", ".join(claimed_names[:4])))
    if c.theta is not None:
        pct = (
            f"{round(percentile * 100)}-й перцентиль категории"
            if percentile is not None
            else f"θ = {c.theta:+.2f}"
        )
        reasons.append(Reason("positive" if ps_parts["test"] >= 0.6 else "neutral", f"Тест: {pct}"))
        trust = trust_level(c)
        if trust:
            reasons.append(Reason(*TRUST_REASON[trust]))
    reasons.extend(exp_reasons)
    if c.fsp is None:
        reasons.append(Reason("neutral", "ФСП ID не привязан"))
    elif c.fsp:
        best = max(
            c.fsp,
            key=lambda a: catalog.fsp_weight("levels", a.level) * catalog.fsp_weight("results", a.result),
        )
        res_t = next(x["title"] for x in catalog.fsp["results"] if x["id"] == best.result)
        lvl_t = next(x["title"] for x in catalog.fsp["levels"] if x["id"] == best.level).lower()
        disc = next(
            (d["title"] for d in catalog.fsp["disciplines"] if d["id"] == best.discipline), best.discipline
        )
        extra = f" (+{len(c.fsp) - 1})" if len(c.fsp) > 1 else ""
        reasons.append(
            Reason(
                "positive",
                f"ФСП: {res_t.lower()} — {lvl_t} соревнования, {disc.lower()}, {best.event_date.year}{extra}",
            )
        )
    else:
        reasons.append(Reason("neutral", "ФСП ID привязан, достижений пока нет"))
    if c.tasks_score >= 0.3:
        reasons.append(Reason("positive", "Решает регулярные задания"))
    sal_text = {
        "within": "Ожидания по ЗП в вашей вилке",
        "above": "Ожидания по ЗП ниже вашей вилки",
        "partial": "Вилка частично пересекается с ожиданиями",
        "below": "Вилка ниже ожиданий кандидата",
        "unknown": "Ожидания по ЗП не указаны",
    }[sal_kind]
    reasons.append(
        Reason(
            {
                "within": "positive",
                "above": "positive",
                "partial": "neutral",
                "below": "negative",
                "unknown": "neutral",
            }[sal_kind],
            sal_text,
        )
    )
    if fmt <= 0.5 and need.work_format:
        reasons.append(Reason("negative", "Формат работы не совпадает с предпочтениями"))
    if c.last_active:
        days = (today - c.last_active).days
        reasons.append(
            Reason(
                "positive" if days <= 14 else "neutral",
                "Активен " + ("сегодня" if days <= 0 else f"{days} дн. назад"),
            )
        )
    if adjacent:
        reasons.append(Reason("neutral", f"Соседняя категория: {catalog.grade(c.grade).name}"))
    if gate.get("core", 1.0) < 1.0:
        reasons.append(Reason("negative", "Нет основного стека вакансии: " + ", ".join(core)))
    if missing and gate.get("must", 1.0) < 1.0:
        reasons.append(Reason("negative", "Не закрыто из обязательного: " + ", ".join(missing[:4])))
    elif missing:
        reasons.append(Reason("negative", "Не подтверждено: " + ", ".join(missing[:4])))
    if gate.get("salary", 1.0) < 1.0:
        reasons.append(Reason("negative", "Ожидания по ЗП выше вилки более чем на 15%"))

    return Scored(
        candidate_id=c.id,
        score=round(total, 4),
        profile_strength=round(ps, 4),
        components={k: round(v, 4) for k, v in components.items()},
        details={
            "need_fit": need_fit,
            "coverage": coverage,
            "must_coverage": must_cov,
            "semantic": semantic if semantic is not None else -1,
            "conditions": conditions,
            "freshness": fresh,
            **{f"gate_{k}": v for k, v in gate.items()},
            **ps_parts,
        },
        reasons=reasons,
        missing=missing,
        adjacent=adjacent,
        salary_fit=sal_kind,
    )


# ------------------------------------------------------------------------------- версия 2
#
# Анализ ошибок v1 на бенчмарке (docs/bench.md): треть мест в top-10 занимали кандидаты, которых
# судьи отвергали из-за одного жёсткого расхождения — несовместимый формат, ожидания сильно выше
# вилки, не тот уровень, не закрыты обязательные навыки. В аддитивной формуле такой провал
# перекрывается достоинствами в других компонентах («ИЛИ»), а решение рекрутера устроено как «И».
# Поэтому в v2 условия, уровень и обязательные навыки — мультипликативные «ворота», навыки
# засчитываются частично через граф смежности технологий, а ФСП не компенсирует пробелы
# в обязательных требованиях.


@dataclass(frozen=True)
class WeightsV2:
    fit: float = 0.55  # соответствие навыкам
    profile: float = 0.30  # сила профиля
    freshness: float = 0.15
    must_share: float = 0.8  # доля обязательных требований внутри соответствия
    must_importance: float = 0.6  # важность, с которой технология считается обязательной
    # ворота (множители 0..1)
    gate_format_soft: float = 0.85  # гибрид против офиса/удалёнки
    gate_format_hard: float = 0.45  # офис против удалёнки
    gate_salary_slack: float = 0.15  # ожидания выше вилки до 15% — без штрафа
    gate_salary_slope: float = 1.6
    gate_salary_floor: float = 0.25
    gate_grade_lower: float = 0.65  # кандидат на ступень ниже
    gate_grade_higher: float = 0.8  # на ступень выше: переплата и риск ухода
    gate_must_threshold: float = 0.5  # ниже — дополнительный штраф за пробелы в обязательном
    gate_core: float = 0.25  # нет основного стека вакансии (v6); как нижняя граница вилки
    use_graph: bool = True
    fsp_needs_must: bool = True  # ФСП учитывается пропорционально покрытию обязательного


DEFAULT_WEIGHTS_V2 = WeightsV2()


def tech_credit(
    c: CandidateFeatures, tech: str, cut: float | None = None, use_graph: bool = True
) -> tuple[float, str, str | None]:
    """Зачёт требования `tech`: прямой (как в v1) или через смежную технологию из графа.

    Возвращает (0..1, источник, смежная технология или None).
    """
    from ..nlp.skills import get_skill_graph

    value, src = skill_evidence(c, tech, DEFAULT_WEIGHTS, cut=cut)
    via = None
    for other, share in get_skill_graph().get(tech, ()) if use_graph else ():
        if other in c.claimed:
            ev, _ = skill_evidence(c, other, DEFAULT_WEIGHTS, cut=cut)
            if share * ev > value:
                value, src, via = share * ev, "graph", other
    return value, src, via


def _gate_salary(c: CandidateFeatures, need: Need, w: WeightsV2) -> float:
    top = need.salary_to or need.salary_from
    if not top or not c.salary_from or c.salary_from <= top:
        return 1.0
    gap = (c.salary_from - top) / c.salary_from
    if gap <= w.gate_salary_slack:
        return 1.0
    return max(w.gate_salary_floor, 1.0 - w.gate_salary_slope * (gap - w.gate_salary_slack))


def score_candidate_v2(
    c: CandidateFeatures,
    need: Need,
    today: date,
    *,
    w: WeightsV2 = DEFAULT_WEIGHTS_V2,
    adjacent: bool = False,
    catalog: Catalog | None = None,
    percentile: float | None = None,
) -> Scored:
    catalog = catalog or get_catalog()
    # причины, вилка и прочие пояснения — общие с v1
    base_v1 = score_candidate(c, need, today, adjacent=adjacent, catalog=catalog, percentile=percentile)
    reasons = [r for r in base_v1.reasons if not r.text.startswith("Не подтверждено")]

    cut = catalog.grade(need.grade).cut
    must_num = must_den = plus_num = plus_den = 0.0
    missing: list[str] = []
    via_graph: list[str] = []
    for tech, imp in need.skills.items():
        value, _, via = tech_credit(c, tech, cut, w.use_graph)
        if imp >= w.must_importance:
            must_num += imp * value
            must_den += imp
            if value < 0.5:
                missing.append(tech)
        else:
            plus_num += imp * value
            plus_den += imp
        if via and value >= 0.3:
            via_graph.append(f"{tech} ← {via}")
    must_cov = must_num / must_den if must_den else (plus_num / plus_den if plus_den else 0.5)
    plus_cov = plus_num / plus_den if plus_den else must_cov
    fit = w.must_share * must_cov + (1 - w.must_share) * plus_cov

    _, ps_parts = profile_strength(c, today, DEFAULT_WEIGHTS, catalog)
    # ФСП усиливает профиль, но не компенсирует пробелы в обязательных требованиях
    ps = (
        DEFAULT_WEIGHTS.ps_test * ps_parts["test"]
        + DEFAULT_WEIGHTS.ps_fsp * ps_parts["fsp"] * (must_cov if w.fsp_needs_must else 1.0)
        + DEFAULT_WEIGHTS.ps_tasks * ps_parts["tasks"]
    )
    fresh = freshness(c, today)

    fmt = format_fit(c, need.work_format)
    gates = {
        "format": 1.0 if fmt >= 0.8 else (w.gate_format_soft if fmt >= 0.5 else w.gate_format_hard),
        "salary": _gate_salary(c, need, w),
        "grade": 1.0,
        "must": 1.0 if must_cov >= w.gate_must_threshold else 0.5 + must_cov,
    }
    if adjacent and c.grade:
        lower = catalog.grade_index(c.grade) < catalog.grade_index(need.grade)
        gates["grade"] = w.gate_grade_lower if lower else w.gate_grade_higher
    g = math.prod(gates.values())

    raw = {"need_fit": w.fit * fit, "profile": w.profile * ps, "freshness": w.freshness * fresh}
    components = {k: round(v * g, 4) for k, v in raw.items()}
    total = sum(raw.values()) * g

    if via_graph:
        reasons.append(Reason("neutral", "Смежный опыт: " + ", ".join(via_graph[:3])))
    if missing:
        reasons.append(Reason("negative", "Не закрыто из обязательного: " + ", ".join(missing[:4])))
    if gates["salary"] < 1.0:
        reasons.append(Reason("negative", "Ожидания по ЗП заметно выше вилки"))
    if gates["grade"] < 1.0 and catalog.grade_index(c.grade) > catalog.grade_index(need.grade):
        reasons.append(Reason("neutral", "Уровень выше требуемого: возможна переплата"))

    return Scored(
        candidate_id=c.id,
        score=round(total, 4),
        profile_strength=base_v1.profile_strength,
        components=components,
        details={
            "need_fit": fit,
            "must_coverage": must_cov,
            "plus_coverage": plus_cov,
            "profile_v2": ps,
            "freshness": fresh,
            **{f"gate_{k}": v for k, v in gates.items()},
            **ps_parts,
        },
        reasons=reasons,
        missing=missing,
        adjacent=adjacent,
        salary_fit=base_v1.salary_fit,
    )


def rank(
    candidates: Iterable[CandidateFeatures],
    need: Need,
    today: date,
    *,
    w: Weights = DEFAULT_WEIGHTS,
    catalog: Catalog | None = None,
    version: int = 5,
    w2: WeightsV2 = DEFAULT_WEIGHTS_V2,
) -> list[Scored]:
    """version: 5 — формула v1 + специфичность требований + «ворота» (по умолчанию);
    6 — v5 + жёсткие «ворота» основного стека вакансии;
    7 — v6 + весомый ФСП (`WEIGHTS_V7`) и ФСП как опыт работы (`FSP_YEARS_MAX`); w по умолчанию
    заменяется на `WEIGHTS_V7`;
    1 — исходная аддитивная формула; 2 — граф навыков и «ворота» (экспериментальная)."""
    catalog = catalog or get_catalog()
    if version >= 7 and w is DEFAULT_WEIGHTS:
        w = WEIGHTS_V7
    pool = []
    for c in candidates:
        ok, adj = eligible(c, need, catalog)
        if ok:
            pool.append((c, adj))
    spec_w = specificity([c for c, _ in pool], need.skills) if version in (5, 6, 7) else None
    core = core_stack(need) if version in (6, 7) else ()
    # перцентиль θ внутри собственной категории кандидата (для объяснения)
    by_cat: dict[tuple, list[float]] = {}
    for c, _ in pool:
        if c.theta is not None:
            by_cat.setdefault((c.specialization, c.grade), []).append(c.theta)
    for k in by_cat:
        by_cat[k].sort()
    out = []
    for c, adj in pool:
        pct = None
        peers = by_cat.get((c.specialization, c.grade))
        if c.theta is not None and peers and len(peers) >= 5:
            pct = float(np.searchsorted(peers, c.theta, side="right")) / len(peers)
        if version == 2:
            out.append(
                score_candidate_v2(c, need, today, w=w2, adjacent=adj, catalog=catalog, percentile=pct)
            )
        elif version in (5, 6, 7):
            out.append(
                score_candidate(
                    c,
                    need,
                    today,
                    w=w,
                    adjacent=adj,
                    catalog=catalog,
                    percentile=pct,
                    spec_weights=spec_w,
                    gates=w2,
                    core=core,
                    fsp_experience=version >= 7,
                )
            )
        else:
            out.append(score_candidate(c, need, today, w=w, adjacent=adj, catalog=catalog, percentile=pct))
    out.sort(key=lambda s: (-s.score, s.candidate_id))
    return out


def rank_in_category(
    candidates: Iterable[CandidateFeatures], spec: str, grade: str, today: date, w: Weights = DEFAULT_WEIGHTS
) -> list[tuple[str, float]]:
    """Порядок внутри категории (просмотр базы без описания потребности)."""
    rows = []
    for c in candidates:
        if c.specialization == spec and c.grade == grade and c.search_status != "closed":
            rows.append((c.id, profile_strength(c, today, w)[0]))
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows


@dataclass
class CategorySummary:
    specialization: str
    grade: str
    total: int
    with_fsp: int
    salary_median: int | None
    in_budget_share: float | None
    relation: str  # target / adjacent / alternative


def recommend_categories(
    candidates: Sequence[CandidateFeatures],
    need: Need,
    spec_scores: dict[str, float] | None = None,
    catalog: Catalog | None = None,
) -> list[CategorySummary]:
    """Рекомендованные категории: целевая, соседние по грейду и альтернативные специализации."""
    catalog = catalog or get_catalog()
    g_idx = catalog.grade_index(need.grade)
    targets: list[tuple[str, str, str]] = [(need.specialization, need.grade, "target")]
    for d in (-1, 1):
        g = catalog.grade_by_index(g_idx + d)
        if g:
            targets.append((need.specialization, g.id, "adjacent"))
    if spec_scores:
        for s, p in sorted(spec_scores.items(), key=lambda x: -x[1]):
            if s != need.specialization and p >= 0.15:
                targets.append((s, need.grade, "alternative"))
    out = []
    for spec, grade, rel in targets:
        pool = [
            c
            for c in candidates
            if c.specialization == spec and c.grade == grade and c.search_status != "closed"
        ]
        sal = sorted(c.salary_from for c in pool if c.salary_from)
        in_budget = None
        top = need.salary_to or need.salary_from
        if top and sal:
            in_budget = sum(1 for s in sal if s <= top) / len(sal)
        out.append(
            CategorySummary(
                specialization=spec,
                grade=grade,
                total=len(pool),
                with_fsp=sum(1 for c in pool if c.fsp),
                salary_median=int(np.median(sal)) if sal else None,
                in_budget_share=in_budget,
                relation=rel,
            )
        )
    return out
