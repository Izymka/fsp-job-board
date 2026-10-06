"""Статистика бенчмарка: метрики ранжирования при неполной разметке и согласие асессоров.

* nDCG@k *condensed* (Sakai, 2007): неразмеченные кандидаты удаляются из выдачи до подсчёта —
  стандартный способ не наказывать систему за то, что её находки не попали в пул.
* Доверительные интервалы — бутстреп по потребностям; значимость разницы систем — парный
  рандомизационный тест (Smucker et al., 2007).
* Согласие — взвешенная (квадратичная) κ Коэна для пары оценщиков и α Криппендорфа
  (интервальная метрика) для группы.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from ..validation.assessment import cohen_kappa

K = 10


def dcg(gains: Sequence[float]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_condensed(ranking: Sequence[str], qrels: dict[str, int], k: int = K) -> float | None:
    """qrels — метки только размеченных кандидатов этой потребности. None — нет релевантных."""
    judged = [qrels[c] for c in ranking if c in qrels][:k]
    ideal = sorted(qrels.values(), reverse=True)[:k]
    idcg = dcg(ideal)
    if idcg <= 0:
        return None
    return dcg(judged) / idcg


def precision_condensed(
    ranking: Sequence[str], qrels: dict[str, int], k: int = K, rel: int = 2
) -> float | None:
    judged = [qrels[c] for c in ranking if c in qrels][:k]
    if not judged:
        return None
    return sum(g >= rel for g in judged) / k


def judged_at_k(ranking: Sequence[str], qrels: dict[str, int], k: int = K) -> float:
    top = list(ranking[:k])
    return sum(c in qrels for c in top) / max(1, len(top))


def bootstrap_ci(
    values: Sequence[float], n: int = 5000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float]:
    v = np.asarray(values, dtype=float)
    if len(v) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = v[rng.integers(0, len(v), size=(n, len(v)))].mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def randomization_test(a: Sequence[float], b: Sequence[float], n: int = 20000, seed: int = 0) -> float:
    """Двусторонний парный рандомизационный тест для средней разницы по потребностям."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    if len(d) == 0 or np.allclose(d, 0):
        return 1.0
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n, len(d)))
    null = np.abs((signs * d).mean(axis=1))
    return float((np.sum(null >= abs(d.mean()) - 1e-12) + 1) / (n + 1))


def weighted_kappa(a: Sequence[int], b: Sequence[int], k: int = 4) -> float:
    return cohen_kappa(list(a), list(b), k, weighted=True)


def kappa(a: Sequence[int], b: Sequence[int], k: int = 4) -> float:
    return cohen_kappa(list(a), list(b), k, weighted=False)


def krippendorff_alpha_interval(units: dict[str, dict[str, int]]) -> float:
    """units: объект → {оценщик: метка}. Интервальная α; объекты с одной оценкой не учитываются."""
    values = [list(v.values()) for v in units.values() if len(v) >= 2]
    if not values:
        return float("nan")
    n = sum(len(v) for v in values)
    d_o = (
        sum(
            sum((x - y) ** 2 for i, x in enumerate(v) for j, y in enumerate(v) if i != j) / (len(v) - 1)
            for v in values
        )
        / n
    )
    allv = np.array([x for v in values for x in v], dtype=float)
    # Σ_{i≠j} (x_i − x_j)² = 2n·Σx² − 2(Σx)²
    d_e = (2 * n * float(np.sum(allv**2)) - 2 * float(np.sum(allv)) ** 2) / (n * (n - 1))
    return float(1 - d_o / d_e) if d_e > 0 else float("nan")


def kendall_tau(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (x[i] - x[j]) * (y[i] - y[j])
            conc += s > 0
            disc += s < 0
    return (conc - disc) / max(1, conc + disc)


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    from scipy.stats import spearmanr

    return float(spearmanr(x, y).statistic)
