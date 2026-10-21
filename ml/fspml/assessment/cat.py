"""Классификационное адаптивное тестирование (CAT) на заявленный грейд.

Задача теста — не измерить θ с максимальной точностью, а принять решение «способность выше
порога заявленного грейда или нет». Поэтому:

* задания подбираются по максимуму информации Фишера в точке порога, решение по которому
  сейчас наиболее неопределённо (заявленный грейд или следующий — для предложения повышения);
* первые `warmup` заданий нацелены на порог заявленного грейда (самооценка — хорошая стартовая точка);
* состав теста балансируется по blueprint (ядро специализации + модули стека кандидата, см.
  `blueprint.py`, или навыки вакансии);
* каждый навык состава получает не меньше `cover_min_items` заданий: иначе его подоценка — «нет
  данных», а подтверждённые тестом навыки — главный сигнал подбора; когда до `min_items` остаётся
  столько же заданий, сколько не хватает до покрытия, выбор ограничивается непокрытыми навыками;
* экспозиция контролируется выбором случайного из top-k по информации (randomesque) и потолком
  частоты показа семейства;
* остановка — когда P(θ > порог) ∉ (1 − conf, conf), задано не меньше `min_items` и навыки покрыты,
  либо по `max_items`. conf = 0.85, а не 0.95: решение принимается при P ≥ 0.6, и задания сверх
  уверенности 0.85 почти никогда не меняют итог — они только удлиняли онбординг (35 → 29 заданий
  при той же точности, docs/validation.md, «Правило остановки»).

Все функции чистые: состояние попытки — это список ответов, его легко хранить в БД.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from ..catalog import Catalog, get_catalog
from .irt import ItemParams, information, posterior
from .items import Family


@dataclass(frozen=True)
class CatConfig:
    min_items: int = 10
    max_items: int = 25
    # выбрано перебором на сидах отбора (не отчётных): минимум заданий за онбординг при точности и
    # согласии ретеста не ниже прежних и завышении ≤ 5% (было 0.95)
    stop_confidence: float = 0.85
    pass_probability: float = 0.6  # выбрано по валидации: макс. точность при завышении грейда ≤ 5%
    # Повышение требует большей уверенности, чем подтверждение: работодатели видят кандидата в
    # категории, и ложное повышение дороже ложного отказа (повтор через 14 дней). Пороги повышения
    # подобраны по валидации: главная ошибка прежних 0.75 / 0.8 — занижение сильных кандидатов;
    # 0.70 / 0.5 сдвигают баланс при завышении ≤ 5%. 0.70, а не 0.65: с более короткой остановкой
    # (stop_confidence) при 0.65 завышение растёт на 0.5 п.п.
    pass_probability_upgrade: float = 0.70
    upgrade_probability: float = 0.5
    warmup: int = 3
    randomesque: int = 4
    max_exposure: float = 0.35
    # Семейства прошлых попыток: 0 — только если в навыке не осталось новых; >0 — конкурируют
    # с новыми с информацией, умноженной на этот коэффициент.
    seen_info_factor: float = 0.0
    prior_mean: float = 0.0
    prior_sd: float = 1.0
    # Сдвиг априорного среднего θ на силу подтверждённых достижений ФСП (0..1, `fsp_strength`):
    # достижения из реестра — независимое свидетельство практического уровня, их нельзя заявить
    # самому (в отличие от самооценки грейда). Решение по-прежнему принимают ответы; без истории
    # ФСП приор прежний — штрафа нет.
    fsp_prior_shift: float = 0.8
    # подоценки навыков
    skill_prior_sd: float = 0.6
    skill_min_items: int = 2
    skill_confirm_probability: float = 0.7
    # покрытие: минимум заданий на каждый навык состава до остановки (0 — без требования)
    cover_min_items: int = 2
    # накопление ответов предыдущих попыток онбординга (та же шкала θ)
    min_items_with_carry: int = 6
    max_items_with_carry: int = 20


DEFAULT_CONFIG = CatConfig()


def with_fsp_prior(config: CatConfig, fsp_strength: float) -> CatConfig:
    """Конфигурация попытки кандидата с достижениями ФСП: приор θ сдвинут на `fsp_prior_shift · сила`."""
    if fsp_strength <= 0 or config.fsp_prior_shift == 0:
        return config
    return replace(config, prior_mean=config.prior_mean + config.fsp_prior_shift * min(fsp_strength, 1.0))


@dataclass(frozen=True)
class Response:
    family_id: str
    skill: str
    params: ItemParams
    correct: bool


@dataclass(frozen=True)
class SkillScore:
    skill: str
    n_items: int
    n_correct: int
    theta: float | None
    se: float | None
    p_at_grade: float | None
    status: Literal["confirmed", "uncertain", "weak", "no_data"]


@dataclass(frozen=True)
class CatResult:
    theta: float
    se: float
    n_items: int
    claimed_grade: str
    p_claimed: float
    p_next: float | None
    decision: Literal["confirmed", "not_confirmed"]
    suggestion: Literal["upgrade", "downgrade"] | None
    estimated_grade: str
    skills: dict[str, SkillScore] = field(default_factory=dict)


@dataclass(frozen=True)
class CatPlan:
    """Неизменяемые параметры попытки: что и на какой грейд тестируем."""

    blueprint: dict[str, float]
    claimed_grade: str
    config: CatConfig = DEFAULT_CONFIG
    kind: Literal["initial", "upgrade", "downgrade", "refresh"] = "initial"
    # Ответы предыдущих попыток того же онбординга: учитываются в оценке θ и в остановке,
    # их семейства не повторяются. Тест «на уровень ниже/выше» продолжает измерение, а не
    # начинает с нуля — это повышает точность решения на границах грейдов.
    carry: tuple[Response, ...] = ()
    # Семейства, которые кандидат уже видел в прошлых попытках (не учитываются в θ, в отличие от
    # carry). Внутри навыка выбираются в последнюю очередь: повторная попытка идёт на параллельной
    # форме, а не на тех же шаблонах с другими числами.
    seen: frozenset[str] = frozenset()

    def limits(self) -> tuple[int, int]:
        if self.carry:
            return self.config.min_items_with_carry, self.config.max_items_with_carry
        return self.config.min_items, self.config.max_items

    def cuts(self, catalog: Catalog) -> tuple[float, float | None]:
        g = catalog.grade(self.claimed_grade)
        nxt = catalog.grade_by_index(g.order + 1)
        return g.cut, (nxt.cut if nxt else None)


def _pairs(responses: Iterable[Response]) -> list[tuple[ItemParams, bool]]:
    return [(r.params, r.correct) for r in responses]


def coverage_gap(
    responses: Sequence[Response], plan: CatPlan, bank: Sequence[Family] | None = None
) -> dict[str, int]:
    """Сколько заданий не хватает каждому навыку состава до `cover_min_items`.

    Если передан банк, требование не превышает число семейств навыка в нём (выведенные из ротации
    семейства не должны растягивать тест до `max_items`).
    """
    need = plan.config.cover_min_items
    if need <= 0:
        return {}
    in_bank = Counter(f.skill for f in bank) if bank is not None else None
    counts = Counter(r.skill for r in [*plan.carry, *responses])
    gap = {}
    for s in plan.blueprint:
        req = need if in_bank is None else min(need, in_bank.get(s, 0))
        if counts.get(s, 0) < req:
            gap[s] = req - counts.get(s, 0)
    return gap


def estimate(responses: Sequence[Response], config: CatConfig = DEFAULT_CONFIG, extra_loglik=None):
    return posterior(_pairs(responses), config.prior_mean, config.prior_sd, extra_loglik)


def select_next(
    responses: Sequence[Response],
    bank: Sequence[Family],
    plan: CatPlan,
    rng: random.Random,
    *,
    exposure: dict[str, float] | None = None,
    catalog: Catalog | None = None,
) -> Family | None:
    """Выбрать следующее семейство или None, если подходящих не осталось."""
    catalog = catalog or get_catalog()
    cfg = plan.config
    used = {r.family_id for r in responses} | {r.family_id for r in plan.carry}
    keys = {f.id: f.content_key for f in bank}
    used_keys = {keys.get(fid, fid) for fid in used}
    exposure = exposure or {}
    candidates = [f for f in bank if f.skill in plan.blueprint and f.id not in used]
    # семейство из уже выданной группы — тот же вопрос другими словами; снимаем запрет, только
    # если иначе выбирать не из чего
    candidates = [f for f in candidates if f.content_key not in used_keys] or candidates
    eligible = [f for f in candidates if exposure.get(f.id, 0.0) < cfg.max_exposure]
    if not eligible:
        # потолок экспозиции не должен обрывать тест: снимаем его, если иначе выбирать не из чего
        eligible = candidates
    if not eligible:
        return None

    # 1. Балансировка содержания: навык с наибольшим дефицитом относительно blueprint.
    #    Ближе к минимальной длине — только навыки, которым не хватает заданий до покрытия.
    n = len(responses)
    counts = Counter(r.skill for r in responses)
    available_skills = {f.skill for f in eligible}
    gap = coverage_gap(responses, plan, bank)
    if gap and n + sum(gap.values()) >= plan.limits()[0]:
        available_skills = {s for s in available_skills if s in gap} or available_skills
    deficits = {s: plan.blueprint[s] * (n + 1) - counts.get(s, 0) for s in available_skills}
    best = max(deficits.values())
    skill = rng.choice(sorted(s for s, d in deficits.items() if d >= best - 1e-9))

    # 2. Точка нацеливания: порог, решение по которому наиболее неопределённо.
    claimed_cut, next_cut = plan.cuts(catalog)
    if n < cfg.warmup and not plan.carry:
        target = claimed_cut
    else:
        post = estimate([*plan.carry, *responses], cfg)
        p_claimed = post.prob_above(claimed_cut)
        candidates = [(abs(p_claimed - 0.5), claimed_cut)]
        if next_cut is not None and p_claimed > 0.5:
            candidates.append((abs(post.prob_above(next_cut) - 0.5), next_cut))
        target = min(candidates)[1]

    # 3. Максимум информации в точке + randomesque среди top-k. Семейства прошлых попыток —
    #    только если в навыке не осталось новых.
    in_skill = [f for f in eligible if f.skill == skill]
    seen_keys = {keys.get(fid, fid) for fid in plan.seen}
    fresh = [f for f in in_skill if f.content_key not in seen_keys]
    if cfg.seen_info_factor > 0:
        fresh = in_skill

    def score(f: Family) -> float:
        info = float(information(target, f.a, f.b, f.c))
        return info * cfg.seen_info_factor if f.content_key in seen_keys else info

    pool = sorted(fresh or in_skill, key=score, reverse=True)
    return rng.choice(pool[: cfg.randomesque])


def should_stop(
    responses: Sequence[Response],
    plan: CatPlan,
    *,
    catalog: Catalog | None = None,
    bank: Sequence[Family] | None = None,
) -> bool:
    catalog = catalog or get_catalog()
    cfg = plan.config
    n = len(responses)
    lo, hi = plan.limits()
    if n >= hi:
        return True
    if n < lo or coverage_gap(responses, plan, bank):
        return False
    claimed_cut, _ = plan.cuts(catalog)
    p = estimate([*plan.carry, *responses], cfg).prob_above(claimed_cut)
    return p >= cfg.stop_confidence or p <= 1 - cfg.stop_confidence


def skill_scores(
    responses: Sequence[Response], grade_cut: float, config: CatConfig = DEFAULT_CONFIG
) -> dict[str, SkillScore]:
    """Иерархическая EAP-оценка навыков.

    Приор навыка — N(θ_без_навыка, σ²): общий уровень, оценённый по *остальным* заданиям
    (чтобы не учитывать одни и те же ответы дважды). При малом числе заданий оценка навыка
    сжимается к общему уровню — статус не «скачет» при повторном прохождении.
    """
    out: dict[str, SkillScore] = {}
    for skill in sorted({r.skill for r in responses}):
        own = [r for r in responses if r.skill == skill]
        rest = [r for r in responses if r.skill != skill]
        n_correct = sum(r.correct for r in own)
        if len(own) < config.skill_min_items:
            out[skill] = SkillScore(skill, len(own), n_correct, None, None, None, "no_data")
            continue
        prior_mean = estimate(rest, config).mean if rest else config.prior_mean
        post = posterior(_pairs(own), prior_mean, config.skill_prior_sd)
        p = post.prob_above(grade_cut)
        if p >= config.skill_confirm_probability:
            status = "confirmed"
        elif p <= 1 - config.skill_confirm_probability:
            status = "weak"
        else:
            status = "uncertain"
        out[skill] = SkillScore(skill, len(own), n_correct, post.mean, post.sd, p, status)
    return out


def decide(
    responses: Sequence[Response], plan: CatPlan, *, catalog: Catalog | None = None, extra_loglik=None
) -> CatResult:
    """Решение о грейде. extra_loglik — правдоподобие практического кейса (Middle+) на сетке θ:
    тест знаний и кейс объединяются в одном апостериорном распределении."""
    catalog = catalog or get_catalog()
    cfg = plan.config
    claimed_cut, next_cut = plan.cuts(catalog)
    responses = [*plan.carry, *responses]
    post = estimate(responses, cfg, extra_loglik)
    p_claimed = post.prob_above(claimed_cut)
    p_next = post.prob_above(next_cut) if next_cut is not None else None
    threshold = cfg.pass_probability_upgrade if plan.kind == "upgrade" else cfg.pass_probability
    confirmed = p_claimed >= threshold
    suggestion = None
    if confirmed and p_next is not None and p_next >= cfg.upgrade_probability:
        suggestion = "upgrade"
    elif not confirmed and catalog.grade(plan.claimed_grade).order > 0:
        suggestion = "downgrade"
    return CatResult(
        theta=post.mean,
        se=post.sd,
        n_items=len(responses),
        claimed_grade=plan.claimed_grade,
        p_claimed=p_claimed,
        p_next=p_next,
        decision="confirmed" if confirmed else "not_confirmed",
        suggestion=suggestion,
        estimated_grade=catalog.grade_for_theta(post.mean).id,
        skills=skill_scores(responses, claimed_cut, cfg),
    )
