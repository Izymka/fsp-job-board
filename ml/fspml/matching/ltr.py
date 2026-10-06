"""Версия 3 механики: ранжировщик LambdaMART, дистиллированный из разметки LLM-асессоров.

Идея «учитель → ученик»: LLM-асессоры офлайн размечают пары «вакансия — кандидат» по рубрике,
а компактный градиентный бустинг учится воспроизводить их порядок на понятных признаках.
В работе приложения модель исполняется локально за миллисекунды, без облака и без передачи ПДн.

Признаки — те же величины, что объясняют выдачу в v2 (покрытие обязательных навыков с учётом
графа, разрыв по зарплате, формат, уровень, тест, ФСП). На все признаки, где направление влияния
очевидно, наложены **монотонные ограничения**: модель не может понизить кандидата за более
высокий тест, большее покрытие навыков или более низкие ожидания по зарплате. Это защита от
выученных артефактов разметки и прямое выполнение требования ТЗ «подтверждённые выше».
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..catalog import DATA_DIR, Catalog, get_catalog
from .scoring import (
    CandidateFeatures,
    Need,
    Reason,
    Scored,
    format_fit,
    freshness,
    score_candidate_v2,
)

MODEL_PATH = DATA_DIR / "ranker_v3.txt"

# (имя, монотонность: +1 растёт, −1 убывает, 0 — без ограничения, подпись для объяснения)
FEATURES: list[tuple[str, int, str]] = [
    ("must_coverage", 1, "Обязательные навыки"),
    ("plus_coverage", 1, "Навыки «будет плюсом»"),
    ("test", 1, "Результат теста"),
    ("fsp", 1, "Достижения ФСП"),
    ("tasks", 1, "Регулярные задания"),
    ("freshness", 1, "Активность"),
    ("format_fit", 1, "Формат работы"),
    ("salary_gap", -1, "Ожидания по ЗП относительно вилки"),
    ("grade_diff", 0, "Уровень относительно вакансии"),
    ("active_search", 1, "Активно ищет"),
]
FEATURE_NAMES = [f[0] for f in FEATURES]
MONOTONE = [f[1] for f in FEATURES]
TITLES = {f[0]: f[2] for f in FEATURES}

LGBM_PARAMS = dict(
    objective="lambdarank",
    n_estimators=300,
    learning_rate=0.05,
    num_leaves=7,
    min_child_samples=15,
    subsample=0.9,
    subsample_freq=1,
    colsample_bytree=0.9,
    reg_lambda=1.0,
    monotone_constraints=MONOTONE,
    monotone_constraints_method="advanced",
    verbose=-1,
    random_state=0,
)


def features(
    c: CandidateFeatures, need: Need, today: date, *, adjacent: bool = False, catalog: Catalog | None = None
) -> dict[str, float]:
    catalog = catalog or get_catalog()
    s2 = score_candidate_v2(c, need, today, adjacent=adjacent, catalog=catalog)
    d = s2.details
    top = need.salary_to or need.salary_from
    gap = 0.0
    if top and c.salary_from:
        gap = max(-1.0, min(1.0, (c.salary_from - top) / c.salary_from))
    gdiff = 0.0
    if c.grade:
        gdiff = float(catalog.grade_index(c.grade) - catalog.grade_index(need.grade))
    return {
        "must_coverage": d["must_coverage"],
        "plus_coverage": d["plus_coverage"],
        "test": d["test"],
        "fsp": d["fsp"],
        "tasks": d["tasks"],
        "freshness": freshness(c, today),
        "format_fit": format_fit(c, need.work_format),
        "salary_gap": gap,
        "grade_diff": gdiff,
        "active_search": 1.0 if c.search_status == "active" else 0.0,
    }


def matrix(rows: list[dict[str, float]]) -> np.ndarray:
    return np.array([[r[n] for n in FEATURE_NAMES] for r in rows], dtype=float)


def train(X: np.ndarray, y: np.ndarray, groups: list[int]):
    import lightgbm as lgb

    model = lgb.LGBMRanker(**LGBM_PARAMS)
    model.fit(X, y, group=groups)
    return model


def save(model, path: Path = MODEL_PATH) -> None:
    model.booster_.save_model(str(path))


@lru_cache(maxsize=1)
def load(path: Path = MODEL_PATH):
    import lightgbm as lgb

    if not path.exists():
        return None
    return lgb.Booster(model_file=str(path))


@dataclass
class Explained:
    score: float
    contributions: dict[str, float]  # вклад признака в балл (SHAP), сумма + bias = score


def predict(booster, X: np.ndarray) -> np.ndarray:
    return booster.predict(X)


def explain(booster, x: np.ndarray) -> Explained:
    contrib = booster.predict(x.reshape(1, -1), pred_contrib=True)[0]
    return Explained(float(contrib.sum()), dict(zip(FEATURE_NAMES, map(float, contrib[:-1]))))


def score_candidate_v3(
    c: CandidateFeatures,
    need: Need,
    today: date,
    *,
    adjacent: bool = False,
    catalog: Catalog | None = None,
    percentile: float | None = None,
    booster=None,
) -> Scored:
    """Балл v3 с объяснением: причины из v2 + точные вклады признаков по SHAP."""
    catalog = catalog or get_catalog()
    booster = booster or load()
    s2 = score_candidate_v2(c, need, today, adjacent=adjacent, catalog=catalog, percentile=percentile)
    if booster is None:  # модель не обучена — работаем как v2
        return s2
    f = features(c, need, today, adjacent=adjacent, catalog=catalog)
    ex = explain(booster, matrix([f])[0])
    # балл LambdaMART не ограничен; для отображения переводим в 0..1 логистой
    shown = 1.0 / (1.0 + math.exp(-ex.score))
    top = sorted(ex.contributions.items(), key=lambda kv: -abs(kv[1]))[:3]
    reasons = list(s2.reasons)
    reasons.append(
        Reason(
            "neutral",
            "Сильнее всего на место повлияли: "
            + ", ".join(f"{TITLES[k].lower()} ({'+' if v >= 0 else '−'})" for k, v in top),
        )
    )
    return Scored(
        candidate_id=c.id,
        score=round(shown, 4),
        profile_strength=s2.profile_strength,
        components=s2.components,
        details={**s2.details, **{f"shap_{k}": v for k, v in ex.contributions.items()}, "raw_v3": ex.score},
        reasons=reasons,
        missing=s2.missing,
        adjacent=adjacent,
        salary_fit=s2.salary_fit,
    )
