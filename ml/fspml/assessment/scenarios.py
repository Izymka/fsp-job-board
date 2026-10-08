"""Практические кейсы второго этапа теста (Middle+): банк, экземпляры, выбор уточняющего вопроса,
перевод оценки по рубрике в вероятностную модель IRT.

Как кейс встраивается в решение о грейде. Ответ оценивается по рубрике (критерии 0–3, см.
`scenario_grader`), итог — порядковая категория k ∈ {0, 1, 2, 3}: «не справился / частично /
соответствует уровню / сверх уровня». Категория — это политомический ответ в модели
градуированных ответов Самеджимы (GRM, 1969):

    P(k ≥ j | θ) = σ(a · (θ − b_j)),  j = 1..3

Пороги b_j привязаны к порогу грейда кейса: b_2 = cut (кандидат ровно на пороге грейда с
вероятностью 1/2 даёт ответ «соответствует уровню» и выше), b_1 = cut − 1.0, b_3 = cut + 0.9.
Правдоподобие кейса умножается на апостериорное распределение θ после теста знаний — решение о
грейде принимается по общей шкале, без отдельных «весов». Параметры экспертные, как и у
семейств заданий; уточняются по пилоту (MML-EM для GRM) — честно указано в документации.

**Отраслевые и предметные обёртки (skins).** Один кейс — один скелет: критерии, веса, вопросы
и параметры GRM общие. Обёртка меняет только сюжет (заголовок, контекст, задачу) и значения
переменных `{{var}}`, которые подставляются и в рубрику, и в её ключевые слова. CV-специалист из
спорта получает «детектор фолов по видео» вместо «оттока клиентов банка» — те же ловушки
(дисбаланс, утечка будущего, группировка по матчу вместо клиента), та же оценка. Обёртка
выбирается по направлению кандидата (2 балла) и отраслям из опроса (1 балл); при повторе кейса
берётся ещё не виденная обёртка.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import yaml

from ..catalog import DATA_DIR, get_catalog
from .irt import GRID

SCENARIO_GRADES = ("middle", "senior", "lead")
MAIN_TIME_LIMIT = {"middle": 900, "senior": 1080, "lead": 1080}  # секунды
PROBE_TIME_LIMIT = 120
PROBE_MIX = 0.3  # вклад уточняющего вопроса в итоговую оценку кейса
CATEGORY_EDGES = (0.35, 0.6, 0.8)  # итог 0..1 → категория 0..3
GRM_A = 1.8
GRM_OFFSETS = (-1.0, 0.0, 0.9)


@dataclass(frozen=True)
class Criterion:
    id: str
    title: str
    weight: float
    expect: str
    strong: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class Probe:
    criterion: str | None  # None — «смена требований» (twist)
    text: str
    expect: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class Skin:
    id: str
    title: str
    context: str
    task: str | None = None
    code: str | None = None
    industries: tuple[str, ...] = ()
    directions: tuple[str, ...] = ()
    vars: dict[str, str] = field(default_factory=dict)

    def score(self, industries: Sequence[str], directions: Sequence[str]) -> int:
        return 2 * len(set(self.directions) & set(directions)) + (
            1 if set(self.industries) & set(industries) else 0
        )


@dataclass(frozen=True)
class Scenario:
    id: str
    spec: str
    grade: str
    skill: str
    title: str
    context: str
    task: str
    code: str | None
    code_lang: str | None
    criteria: tuple[Criterion, ...]
    probes: tuple[Probe, ...]
    twist: Probe | None
    params: dict[str, list] = field(default_factory=dict)
    derived: dict[str, str] = field(default_factory=dict)
    vars: dict[str, str] = field(default_factory=dict)  # сюжетные переменные базовой версии
    skins: tuple[Skin, ...] = ()
    industries: tuple[str, ...] = ()  # сюжет базовой версии: отрасли и направления
    directions: tuple[str, ...] = ()

    @property
    def time_limit(self) -> int:
        return MAIN_TIME_LIMIT[self.grade]

    def skin(self, skin_id: str | None) -> Skin | None:
        return next((k for k in self.skins if k.id == skin_id), None) if skin_id else None

    def instance(self, seed: int, skin: str | None = None) -> ScenarioInstance:
        """Экземпляр кейса: параметры по seed, сюжет — базовый или обёртки `skin`."""
        rng = random.Random(seed)
        values: dict = {k: rng.choice(v) for k, v in sorted(self.params.items())}
        for k, expr in self.derived.items():
            values[k] = _eval_simple(expr, values)
        sk = self.skin(skin)
        values.update(self.vars)
        if sk is not None:
            values.update(sk.vars)
        sub = lambda s: _substitute(s, values) if s else s  # noqa: E731
        return ScenarioInstance(
            scenario=self,
            values=values,
            skin=sk.id if sk else None,
            title=sub(sk.title if sk else self.title),
            context=sub(sk.context if sk else self.context),
            task=sub(sk.task if sk and sk.task else self.task),
            code=sub(sk.code if sk and sk.code else self.code),
            criteria=tuple(
                Criterion(
                    c.id, c.title, c.weight, sub(c.expect), sub(c.strong), tuple(sub(k) for k in c.keywords)
                )
                for c in self.criteria
            ),
            probes=tuple(
                Probe(p.criterion, sub(p.text), sub(p.expect), tuple(sub(k) for k in p.keywords))
                for p in self.probes
            ),
            twist=(
                Probe(
                    None,
                    sub(self.twist.text),
                    sub(self.twist.expect),
                    tuple(sub(k) for k in self.twist.keywords),
                )
                if self.twist
                else None
            ),
        )


@dataclass(frozen=True)
class ScenarioInstance:
    scenario: Scenario
    values: dict
    skin: str | None
    title: str
    context: str
    task: str
    code: str | None
    criteria: tuple[Criterion, ...]
    probes: tuple[Probe, ...]
    twist: Probe | None

    @property
    def prompt(self) -> str:
        return f"**{self.title}**\n\n{self.context.strip()}"

    def probe(self, index: int) -> Probe:
        """index ≥ 0 — вопрос из `probes`, −1 — смена требований."""
        if index < 0 and self.twist is not None:
            return self.twist
        return self.probes[index]


def _substitute(text: str, values: dict) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


def _eval_simple(expr: str, values: dict):
    """«a - b», «100 - rate»: только числа, имена параметров, + и −."""
    total, sign = 0, 1
    for tok in re.findall(r"[+-]|\w+", expr):
        if tok in "+-":
            sign = 1 if tok == "+" else -1
            continue
        v = values[tok] if tok in values else int(tok)
        total += sign * int(v)
    return total


@lru_cache(maxsize=1)
def load_scenarios() -> dict[str, Scenario]:
    raw = yaml.safe_load((DATA_DIR / "scenarios.yaml").read_text(encoding="utf-8"))
    out: dict[str, Scenario] = {}
    for r in raw:
        crit = tuple(
            Criterion(
                c["id"],
                c["title"],
                float(c.get("weight", 1.0)),
                c["expect"],
                c.get("strong", ""),
                tuple(c.get("keywords", ())),
            )
            for c in r["criteria"]
        )
        probes = tuple(
            Probe(p["criterion"], p["text"], p["expect"], tuple(p.get("keywords", ())))
            for p in r.get("probes", ())
        )
        tw = r.get("twist")
        out[r["id"]] = Scenario(
            id=r["id"],
            spec=r["spec"],
            grade=r["grade"],
            skill=r["skill"],
            title=r["title"],
            context=r["context"],
            task=r["task"],
            code=r.get("code"),
            code_lang=r.get("code_lang"),
            criteria=crit,
            probes=probes,
            twist=Probe(None, tw["text"], tw["expect"], tuple(tw.get("keywords", ()))) if tw else None,
            params={k: list(v) for k, v in (r.get("params") or {}).items()},
            derived=dict(r.get("derived") or {}),
            vars={k: str(v) for k, v in (r.get("vars") or {}).items()},
            industries=tuple(r.get("industries", ())),
            directions=tuple(r.get("directions", ())),
            skins=tuple(
                Skin(
                    id=k["id"],
                    title=k["title"],
                    context=k["context"],
                    task=k.get("task"),
                    code=k.get("code"),
                    industries=tuple(k.get("industries", ())),
                    directions=tuple(k.get("directions", ())),
                    vars={a: str(b) for a, b in (k.get("vars") or {}).items()},
                )
                for k in r.get("skins", ())
            ),
        )
    return out


def needs_scenario(grade: str) -> bool:
    return grade in SCENARIO_GRADES


def pick_scenario(
    spec: str, grade: str, seed: int, exclude: set[str] | frozenset = frozenset()
) -> Scenario | None:
    """Кейс специализации на заявленный грейд; при нескольких — по seed, не повторяя пройденные."""
    pool = [s for s in load_scenarios().values() if s.spec == spec and s.grade == grade]
    fresh = [s for s in pool if s.id not in exclude] or pool
    if not fresh:
        return None
    return sorted(fresh, key=lambda s: s.id)[seed % len(fresh)]


def pick_skin(
    sc: Scenario,
    seed: int,
    *,
    industries: Sequence[str] = (),
    directions: Sequence[str] = (),
    seen: set[str | None] | frozenset = frozenset(),
) -> str | None:
    """Сюжет кейса для кандидата: обёртка с наибольшим совпадением по направлению и отраслям.

    None — базовая версия. Уже виденные кандидатом версии (seen; None — базовая) выбираются,
    только если новых не осталось; среди равных — по seed.
    """
    base = Skin("", sc.title, sc.context, industries=sc.industries, directions=sc.directions)
    options: list[tuple[int, str | None]] = [(base.score(industries, directions), None)] + [
        (k.score(industries, directions), k.id) for k in sc.skins
    ]
    fresh = [o for o in options if o[1] not in seen] or options
    best = max(score for score, _ in fresh)
    top = sorted((sid for score, sid in fresh if score == best), key=lambda x: x or "")
    return top[seed % len(top)]


def choose_probe(inst: ScenarioInstance, scores: dict[str, int]) -> int:
    """Уточняющий вопрос по самому слабому критерию (у которого есть вопрос).

    Если все критерии раскрыты на уровне грейда (≥ 2) — вопрос «смена требований»: проверяем,
    что кандидат понимает своё решение, а не пересказывает готовое.
    """
    weights = {c.id: c.weight for c in inst.criteria}
    with_probe = [(i, p) for i, p in enumerate(inst.probes) if p.criterion in scores]
    if inst.twist is not None and all(v >= 2 for v in scores.values()):
        return -1
    if not with_probe:
        return -1 if inst.twist is not None else 0
    i, _ = min(
        with_probe, key=lambda ip: (scores[ip[1].criterion], -weights.get(ip[1].criterion, 1.0), ip[0])
    )
    return i


def total_score(inst: ScenarioInstance, scores: dict[str, int], probe_score: int | None) -> float:
    """Итог кейса 0..1: взвешенные критерии + вклад уточняющего вопроса."""
    wsum = sum(c.weight for c in inst.criteria) or 1.0
    main = sum(c.weight * scores.get(c.id, 0) / 3 for c in inst.criteria) / wsum
    if probe_score is None:
        return main
    return (1 - PROBE_MIX) * main + PROBE_MIX * probe_score / 3


def category(total: float) -> int:
    return int(sum(total >= e for e in CATEGORY_EDGES))


CATEGORY_TITLES = ("не справился", "частично", "соответствует уровню", "сверх уровня")


@dataclass(frozen=True)
class GrmParams:
    a: float
    thresholds: tuple[float, float, float]


def grm_params(grade: str) -> GrmParams:
    cut = get_catalog().grade(grade).cut
    return GrmParams(GRM_A, tuple(cut + o for o in GRM_OFFSETS))  # type: ignore[arg-type]


def grm_prob(theta, params: GrmParams, k: int) -> np.ndarray:
    """P(категория = k | θ) в модели градуированных ответов."""
    theta = np.asarray(theta, dtype=float)

    def above(j: int):
        if j <= 0:
            return np.ones_like(theta)
        if j > len(params.thresholds):
            return np.zeros_like(theta)
        return 1.0 / (1.0 + np.exp(-np.clip(params.a * (theta - params.thresholds[j - 1]), -35, 35)))

    return np.clip(above(k) - above(k + 1), 1e-9, 1.0)


def grm_loglik(responses: list[tuple[GrmParams, int]]) -> np.ndarray:
    ll = np.zeros_like(GRID)
    for params, k in responses:
        ll += np.log(grm_prob(GRID, params, k))
    return ll
