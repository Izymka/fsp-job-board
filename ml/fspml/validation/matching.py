"""Валидация механики подбора на тестовом наборе пар «потребность – кандидат».

Эталон — градуированная релевантность 0–3 по скрытой истине (population.true_relevance).
Системы видят только наблюдаемое: категорию и подоценки из *симулированного* теста,
заявленный стек (с накруткой), текст резюме, достижения ФСП, условия.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import numpy as np

from ..catalog import get_catalog
from ..matching.baselines import BM25, random_order
from ..matching.scoring import (
    DEFAULT_WEIGHTS,
    DEFAULT_WEIGHTS_V2,
    CandidateFeatures,
    Need,
    Weights,
    WeightsV2,
    rank,
)
from ..nlp.embed import HashingEmbedder
from .assessment import TrueBank, simulate_onboarding
from .population import TODAY, TrueCandidate, TrueNeed, accept_probability, true_relevance

K = 10


@dataclass
class Observed:
    features: list[CandidateFeatures]
    by_id: dict[str, TrueCandidate]


def observe(
    cands: Sequence[TrueCandidate], truth: TrueBank, seed: int = 21, *, legacy: bool = False
) -> Observed:
    """Прогоняет каждого кандидата через онбординг-тест и собирает наблюдаемые признаки.

    legacy=True — прежний общий состав теста: на нём построены карточки размеченных бенчмарков.
    """
    rng = random.Random(seed)
    emb = HashingEmbedder()
    vecs = emb.encode([c.resume_text for c in cands])
    feats = []
    for c, v in zip(cands, vecs):
        ob = simulate_onboarding(c, truth, rng, legacy=legacy)
        last_ok = next(
            (l.result for l in reversed(ob.logs) if l.result.decision == "confirmed"), ob.logs[-1].result
        )
        feats.append(
            CandidateFeatures(
                id=c.id,
                specialization=c.spec,
                grade=ob.grade,
                theta=last_ok.theta,
                theta_se=last_ok.se,
                skill_status={k: s.status for k, s in last_ok.skills.items()},
                skill_theta={k: (s.theta, s.se) for k, s in last_ok.skills.items() if s.theta is not None},
                claimed=set(c.claimed),
                fsp=c.fsp,
                salary_from=c.salary_from,
                salary_to=c.salary_to,
                work_formats=set(c.work_formats),
                industries=set(c.industries),
                search_status=c.search_status,
                last_active=c.last_active,
                tested_at=TODAY,
                about=c.resume_text,
                embedding=v,
                experience_years=c.years if c.relevant_years is not None else None,
                relevant_years=c.relevant_years,
                it_years=c.it_years,
                industry_years=dict(c.industry_years),
            )
        )
    return Observed(feats, {c.id: c for c in cands})


def to_need(n: TrueNeed, emb: HashingEmbedder) -> Need:
    return Need(
        specialization=n.spec,
        grade=n.grade,
        skills=dict(n.skills),
        salary_from=n.salary_from,
        salary_to=n.salary_to,
        work_format=n.work_format,
        industry=n.industry,
        min_years=n.min_years,
        text=n.text,
        embedding=emb.encode([n.text])[0],
    )


def _dcg(gains: Sequence[float]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def metrics_for(ranking: Sequence[str], need: TrueNeed, obs: Observed, rel_cache: dict) -> dict[str, float]:
    rels_all = rel_cache[need.id]
    top = list(ranking[:K])
    rels = [rels_all.get(cid, 0) for cid in top]
    ideal = sorted(rels_all.values(), reverse=True)[:K]
    ndcg = _dcg(rels) / _dcg(ideal) if _dcg(ideal) > 0 else 0.0
    prec = sum(r >= 2 for r in rels) / K
    mrr = next((1 / (i + 1) for i, r in enumerate(rels) if r >= 2), 0.0)
    acc = sum(accept_probability(obs.by_id[cid], need) for cid, r in zip(top, rels) if r >= 2)
    return {"ndcg@10": ndcg, "p@10": prec, "mrr": mrr, "accepted@10": acc}


def _system_rankers(
    obs: Observed, needs: Sequence[TrueNeed]
) -> dict[str, Callable[[TrueNeed, Need], list[str]]]:
    feats = obs.features
    bm25_all = BM25([f.about for f in feats])
    ids = [f.id for f in feats]

    def ours(
        w: Weights = DEFAULT_WEIGHTS,
        transform: Callable[[CandidateFeatures], CandidateFeatures] | None = None,
        version: int = 5,
        w2: WeightsV2 = DEFAULT_WEIGHTS_V2,
    ):
        def run(tn: TrueNeed, need: Need) -> list[str]:
            pool = [transform(f) for f in feats] if transform else feats
            return [s.candidate_id for s in rank(pool, need, TODAY, w=w, version=version, w2=w2)]

        return run

    def bm25_universal(tn, need):
        sc = bm25_all.scores(tn.text)
        return [ids[i] for i in np.argsort(sc)[::-1]]

    def bm25_spec(tn, need):
        sc = bm25_all.scores(tn.text)
        order_ = np.argsort(sc)[::-1]
        return [
            ids[i]
            for i in order_
            if feats[i].specialization == tn.spec and feats[i].search_status != "closed"
        ]

    def cat_random(tn, need):
        pool = [
            f.id
            for f in feats
            if f.specialization == tn.spec and f.grade == tn.grade and f.search_status != "closed"
        ]
        return random_order(pool, seed=hash(tn.id) % 10_000)

    def test_only(tn, need):
        pool = [
            f
            for f in feats
            if f.specialization == tn.spec and f.grade == tn.grade and f.search_status != "closed"
        ]
        return [f.id for f in sorted(pool, key=lambda f: -(f.theta or -9))]

    no_fsp = lambda f: replace(f, fsp=None)  # noqa: E731
    claims_only = lambda f: replace(f, skill_status={}, skill_theta={})  # noqa: E731
    return {
        "ours": ours(),
        "ours_without_fsp": ours(transform=no_fsp),
        "ours_claims_only": ours(transform=claims_only),
        "ours_without_conditions": ours(
            w=replace(DEFAULT_WEIGHTS, conditions=0.0),
            w2=replace(DEFAULT_WEIGHTS_V2, gate_format_soft=1.0, gate_format_hard=1.0, gate_salary_slope=0.0),
        ),
        "ours_v1": ours(version=1),
        "test_only_in_category": test_only,
        "random_in_category": cat_random,
        "bm25_in_specialization": bm25_spec,
        "bm25_universal": bm25_universal,
    }


def evaluate(
    cands: Sequence[TrueCandidate], needs: Sequence[TrueNeed], truth: TrueBank, *, obs: Observed | None = None
) -> dict:
    obs = obs or observe(cands, truth)
    emb = HashingEmbedder()
    rel_cache = {n.id: {c.id: true_relevance(c, n) for c in cands} for n in needs}
    systems = _system_rankers(obs, needs)
    results: dict[str, dict[str, float]] = {}
    for name, ranker in systems.items():
        rows = []
        for tn in needs:
            rows.append(metrics_for(ranker(tn, to_need(tn, emb)), tn, obs, rel_cache))
        results[name] = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
    stuffed_in_top = _stuffing_exposure(obs, needs, emb, rel_cache)
    return {"systems": results, "stuffing": stuffed_in_top, "n_needs": len(needs), "n_candidates": len(cands)}


def without_experience(obs: Observed) -> Observed:
    """Те же кандидаты без истории работы — абляция вклада опыта в подбор."""
    from dataclasses import replace

    feats = [
        replace(f, experience_years=None, relevant_years=None, it_years=None, industry_years={})
        for f in obs.features
    ]
    return Observed(feats, obs.by_id)


def _stuffing_exposure(obs: Observed, needs, emb, rel_cache) -> dict[str, float]:
    """Доля кандидатов с накрученным стеком в топ-10: наша система vs BM25."""
    feats = obs.features
    bm25 = BM25([f.about for f in feats])
    ids = [f.id for f in feats]
    ours_share, bm_share = [], []
    for tn in needs:
        need = to_need(tn, emb)
        top = [s.candidate_id for s in rank(feats, need, TODAY)][:K]
        sc = bm25.scores(tn.text)
        btop = [ids[i] for i in np.argsort(sc)[::-1] if feats[i].specialization == tn.spec][:K]
        req = set(tn.skills)

        def stuffed(cid, req=req):
            return bool(obs.by_id[cid].stuffed & req)

        ours_share.append(np.mean([stuffed(c) for c in top]) if top else 0)
        bm_share.append(np.mean([stuffed(c) for c in btop]) if btop else 0)
    base = np.mean([bool(c.stuffed) for c in obs.by_id.values()])
    return {
        "ours": float(np.mean(ours_share)),
        "bm25_in_specialization": float(np.mean(bm_share)),
        "population_stuffed_share": float(base),
    }


def weight_sensitivity(
    cands, needs, truth, obs: Observed | None = None, factors=(0.5, 1.5)
) -> dict[str, dict[str, float]]:
    obs = obs or observe(cands, truth)
    emb = HashingEmbedder()
    rel_cache = {n.id: {c.id: true_relevance(c, n) for c in cands} for n in needs}
    prepared = [(tn, to_need(tn, emb)) for tn in needs]

    def ndcg_for(w: Weights) -> float:
        vals = []
        for tn, need in prepared:
            ranking = [s.candidate_id for s in rank(obs.features, need, TODAY, w=w)]
            vals.append(metrics_for(ranking, tn, obs, rel_cache)["ndcg@10"])
        return float(np.mean(vals))

    base = ndcg_for(DEFAULT_WEIGHTS)
    out: dict[str, dict[str, float]] = {"_base": {"ndcg@10": base}}
    for field_ in (
        "need_fit",
        "profile",
        "conditions",
        "freshness",
        "ps_test",
        "ps_fsp",
        "coverage_share",
        "claim_base",
        "unclaimed_factor",
        "adjacent_grade_multiplier",
    ):
        out[field_] = {}
        for f in factors:
            value = getattr(DEFAULT_WEIGHTS, field_) * f
            if field_ == "adjacent_grade_multiplier":
                value = min(value, 1.0)  # множитель > 1 поднял бы соседнюю категорию выше целевой
            w = replace(DEFAULT_WEIGHTS, **{field_: value})
            out[field_][f"x{f:g}"] = ndcg_for(w) - base
    return out


def category_accuracy(obs: Observed) -> dict[str, float]:
    """Корректность категоризации: специализация × присвоенный грейд против истины."""
    cat = get_catalog()
    feats = [f for f in obs.features if f.grade]
    exact = np.mean([obs.by_id[f.id].grade == f.grade for f in feats])
    within = np.mean(
        [abs(cat.grade_index(obs.by_id[f.id].grade) - cat.grade_index(f.grade)) <= 1 for f in feats]
    )
    return {
        "categorized_share": len(feats) / len(obs.features),
        "category_exact": float(exact),
        "category_within1": float(within),
    }


def composition_effect(
    cands: Sequence[TrueCandidate], needs: Sequence[TrueNeed], truth: TrueBank, obs: Observed | None = None
) -> dict[str, dict[str, float]]:
    """Разложение 2×2: состав теста (прежний общий / ядро + модули) × формула подбора (v1 / v5).

    Для каждой клетки — NDCG@10 с подоценками навыков из теста и без них (только заявленный стек):
    разница показывает, насколько тест помогает подбору.
    """
    emb = HashingEmbedder()
    rel_cache = {n.id: {c.id: true_relevance(c, n) for c in cands} for n in needs}
    prepared = [(tn, to_need(tn, emb)) for tn in needs]
    out: dict[str, dict[str, float]] = {}
    for legacy in (True, False):
        ob = observe(cands, truth, legacy=True) if legacy else (obs or observe(cands, truth))
        claims = [replace(f, skill_status={}, skill_theta={}) for f in ob.features]
        for version in (1, 5):
            row = {}
            for key, feats in (("with_test", ob.features), ("claims_only", claims)):
                vals = [
                    metrics_for(
                        [s.candidate_id for s in rank(feats, need, TODAY, version=version)], tn, ob, rel_cache
                    )["ndcg@10"]
                    for tn, need in prepared
                ]
                row[key] = float(np.mean(vals))
            out[f"{'legacy' if legacy else 'personal'}/v{version}"] = row
    return out
