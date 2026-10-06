"""Модель IRT 3PL с фиксированным параметром угадывания и EAP-оценка способности на сетке.

P(верно | θ) = c + (1 − c) / (1 + exp(−a(θ − b)))

* a — дискриминативность, b — сложность, c — вероятность угадать (фиксируется форматом
  задания: 1/k для выбора из k, 0 для ввода ответа) — не оценивается, что делает модель
  устойчивой при малом числе ответов.
* θ оценивается EAP (среднее апостериорного распределения) на равномерной сетке:
  это устойчиво при всех верных/неверных ответах (в отличие от MLE) и сразу даёт
  P(θ > порог) для решения о грейде.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GRID = np.linspace(-4.0, 4.0, 161)
_DGRID = GRID[1] - GRID[0]


@dataclass(frozen=True)
class ItemParams:
    a: float
    b: float
    c: float = 0.0


def prob(theta: np.ndarray | float, a: float, b: float, c: float = 0.0) -> np.ndarray:
    z = np.clip(a * (np.asarray(theta, dtype=float) - b), -35, 35)
    return c + (1.0 - c) / (1.0 + np.exp(-z))


def information(theta: np.ndarray | float, a: float, b: float, c: float = 0.0) -> np.ndarray:
    """Информация Фишера 3PL: a² · (q/p) · ((p − c)/(1 − c))²."""
    p = prob(theta, a, b, c)
    q = 1.0 - p
    return (a**2) * (q / np.maximum(p, 1e-12)) * ((p - c) / (1.0 - c)) ** 2


def log_prior(mean: float = 0.0, sd: float = 1.0) -> np.ndarray:
    return -0.5 * ((GRID - mean) / sd) ** 2


def log_likelihood(responses: list[tuple[ItemParams, bool]]) -> np.ndarray:
    ll = np.zeros_like(GRID)
    for params, correct in responses:
        p = np.clip(prob(GRID, params.a, params.b, params.c), 1e-9, 1 - 1e-9)
        ll += np.log(p) if correct else np.log1p(-p)
    return ll


@dataclass(frozen=True)
class Posterior:
    weights: np.ndarray  # нормированные веса на GRID

    @property
    def mean(self) -> float:
        return float(np.sum(GRID * self.weights))

    @property
    def sd(self) -> float:
        m = self.mean
        return float(np.sqrt(np.sum((GRID - m) ** 2 * self.weights)))

    def prob_above(self, cut: float) -> float:
        """P(θ > cut) с линейной интерполяцией внутри ячейки сетки."""
        cdf = np.cumsum(self.weights)
        idx = np.searchsorted(GRID, cut)
        if idx <= 0:
            return 1.0
        if idx >= len(GRID):
            return 0.0
        # доля ячейки idx, лежащая выше cut
        frac = (GRID[idx] - cut) / _DGRID
        below = cdf[idx - 1] + (1 - frac) * self.weights[idx]
        return float(np.clip(1.0 - below, 0.0, 1.0))

    def quantile(self, q: float) -> float:
        cdf = np.cumsum(self.weights)
        return float(np.interp(q, cdf, GRID))


def posterior(
    responses: list[tuple[ItemParams, bool]],
    prior_mean: float = 0.0,
    prior_sd: float = 1.0,
    extra_loglik: np.ndarray | None = None,
) -> Posterior:
    """extra_loglik — правдоподобие других форматов на той же сетке (практический кейс, GRM)."""
    lp = log_prior(prior_mean, prior_sd) + log_likelihood(responses)
    if extra_loglik is not None:
        lp = lp + extra_loglik
    lp -= lp.max()
    w = np.exp(lp)
    return Posterior(w / w.sum())
