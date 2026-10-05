"""Онлайн-перекалибровка параметров семейств по накопленным ответам (MML-EM, Bock–Aitkin).

Стартовые параметры — экспертные (уровень семейства → b, a = 1.3). По мере накопления ответов
параметры a, b уточняются методом маргинального максимального правдоподобия с EM на
квадратурной сетке. Экспертные значения служат априорным распределением (байесовская мода),
поэтому при малом числе ответов параметры не «улетают», а при большом — определяются данными.
Параметр угадывания c фиксирован форматом задания и не оценивается.

Шкала θ закрепляется приором способностей N(0, 1), т.е. относительно популяции кандидатов.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .irt import ItemParams

QGRID = np.linspace(-4, 4, 41)
LOG_PRIOR_Q = -0.5 * QGRID**2


@dataclass(frozen=True)
class CalibrationConfig:
    n_iter: int = 40
    tol: float = 1e-3
    prior_b_sd: float = 1.0
    prior_log_a_sd: float = 0.35
    min_responses: int = 30  # меньше — оставляем экспертные параметры


def _prob(theta, a, b, c):
    return c + (1 - c) / (1 + np.exp(-np.clip(a * (theta - b), -35, 35)))


def calibrate(
    person: Sequence[int],
    item: Sequence[int],
    correct: Sequence[bool],
    priors: Sequence[ItemParams],
    config: CalibrationConfig = CalibrationConfig(),
) -> list[ItemParams]:
    """person/item/correct — разреженная матрица ответов (CAT: каждый видел часть банка)."""
    person = np.asarray(person, dtype=int)
    item = np.asarray(item, dtype=int)
    x = np.asarray(correct, dtype=float)
    n_items = len(priors)
    n_persons = int(person.max()) + 1 if len(person) else 0
    a = np.array([p.a for p in priors], dtype=float)
    b = np.array([p.b for p in priors], dtype=float)
    c = np.array([p.c for p in priors], dtype=float)
    a0, b0 = a.copy(), b.copy()
    counts = np.bincount(item, minlength=n_items)
    active = counts >= config.min_responses

    for _ in range(config.n_iter):
        # E-шаг: апостериор способности каждого кандидата на сетке
        p = np.clip(
            _prob(QGRID[None, :], a[item][:, None], b[item][:, None], c[item][:, None]), 1e-9, 1 - 1e-9
        )
        ll = np.where(x[:, None] > 0.5, np.log(p), np.log1p(-p))
        logpost = np.tile(LOG_PRIOR_Q, (n_persons, 1))
        np.add.at(logpost, person, ll)
        logpost -= logpost.max(axis=1, keepdims=True)
        w = np.exp(logpost)
        w /= w.sum(axis=1, keepdims=True)
        # ожидаемые числа попыток и верных ответов в узлах сетки для каждого задания
        wr = w[person]
        n_jq = np.zeros((n_items, len(QGRID)))
        r_jq = np.zeros((n_items, len(QGRID)))
        np.add.at(n_jq, item, wr)
        np.add.at(r_jq, item, wr * x[:, None])

        # M-шаг: по каждому заданию максимизируем ожидаемое правдоподобие + лог-приор
        max_shift = 0.0
        for j in np.flatnonzero(active):

            def nll(theta_ab, j=j, r=r_jq[j], n=n_jq[j]):
                la, bj = theta_ab
                pj = np.clip(_prob(QGRID, np.exp(la), bj, c[j]), 1e-9, 1 - 1e-9)
                ll_j = np.sum(r * np.log(pj) + (n - r) * np.log1p(-pj))
                lp = (
                    -0.5 * ((la - np.log(a0[j])) / config.prior_log_a_sd) ** 2
                    - 0.5 * ((bj - b0[j]) / config.prior_b_sd) ** 2
                )
                return -(ll_j + lp)

            res = minimize(
                nll,
                x0=[np.log(a[j]), b[j]],
                method="L-BFGS-B",
                bounds=[(np.log(0.2), np.log(4.0)), (-4.0, 4.0)],
            )
            new_a, new_b = float(np.exp(res.x[0])), float(res.x[1])
            max_shift = max(max_shift, abs(new_a - a[j]), abs(new_b - b[j]))
            a[j], b[j] = new_a, new_b
        if max_shift < config.tol:
            break

    return [ItemParams(a=float(a[j]), b=float(b[j]), c=float(c[j])) for j in range(n_items)]
