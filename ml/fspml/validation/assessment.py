"""Валидация механики тестирования на синтетической популяции.

Чтобы валидация не была цикличной, ответы симулируются по *истинной* модели, которая
намеренно отличается от модели оценивания:

* истинная сложность семейства b* = b_ном + N(0, 0.35), дискриминативность a* = a_ном · LogN(0, 0.2);
* сложность каждого экземпляра b_экз = b* + N(0, 0.25) — экземпляры семейства не идеально равны;
* кандидат отвечает с навыко-специфичной способностью θ_навыка = θ + N(0, 0.45) — тест
  многомерен, а модель одномерна;
* угадывание по вариантам ответа реально происходит.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from ..assessment.bank import REGISTRY
from ..assessment.calibration import calibrate
from ..assessment.cat import (
    DEFAULT_CONFIG,
    CatConfig,
    CatPlan,
    CatResult,
    Response,
    decide,
    select_next,
    should_stop,
)
from ..assessment.drift import CusumConfig, run_cusum
from ..assessment.irt import ItemParams, information, prob
from ..assessment.items import Family
from ..catalog import get_catalog
from .population import TrueCandidate


@dataclass
class TrueBank:
    params: dict[str, ItemParams]
    inst_sd: float = 0.25


def make_true_bank(
    seed: int = 3, b_sd: float = 0.35, a_logsd: float = 0.2, inst_sd: float = 0.25
) -> TrueBank:
    rng = np.random.default_rng(seed)
    params = {}
    for fid, f in sorted(REGISTRY.items()):
        params[fid] = ItemParams(
            a=float(f.a * math.exp(rng.normal(0, a_logsd))), b=float(f.b + rng.normal(0, b_sd)), c=f.c
        )
    return TrueBank(params, inst_sd)


# Модель утечки: функция (семейство, вероятность верного) → новая вероятность
LeakFn = Callable[[Family, float], float]


@dataclass
class AttemptLog:
    result: CatResult
    responses: list[Response]
    true_correct_p: list[float] = field(default_factory=list)


def simulate_attempt(
    cand: TrueCandidate,
    grade: str,
    truth: TrueBank,
    rng: random.Random,
    *,
    bank: Sequence[Family] | None = None,
    config: CatConfig = DEFAULT_CONFIG,
    leak: LeakFn | None = None,
    fixed_form: Sequence[Family] | None = None,
    carry: Sequence[Response] = (),
    kind: str = "initial",
) -> AttemptLog:
    cat = get_catalog()
    bank = bank if bank is not None else list(REGISTRY.values())
    plan = CatPlan(
        cat.blueprint(cand.spec, [cand.lang] if cand.lang else None), grade, config, kind, tuple(carry)
    )
    responses: list[Response] = []
    ps: list[float] = []
    form_iter = iter(fixed_form) if fixed_form is not None else None
    while True:
        if form_iter is not None:
            fam = next(form_iter, None)
        else:
            if should_stop(responses, plan, catalog=cat):
                break
            fam = select_next(responses, bank, plan, rng, catalog=cat)
        if fam is None:
            break
        tp = truth.params[fam.id]
        b_inst = tp.b + rng.gauss(0, truth.inst_sd)
        th = cand.skill_theta.get(fam.skill, cand.theta)
        p = float(prob(th, tp.a, b_inst, tp.c))
        if leak is not None:
            p = leak(fam, p)
        ps.append(p)
        responses.append(Response(fam.id, fam.skill, fam.params, rng.random() < p))
    return AttemptLog(decide(responses, plan, catalog=cat), responses, ps)


@dataclass
class OnboardingResult:
    grade: str | None
    theta: float | None
    attempts: int
    items: int
    logs: list[AttemptLog]


def simulate_onboarding(
    cand: TrueCandidate, truth: TrueBank, rng: random.Random, *, pool: bool = False, **kw
) -> OnboardingResult:
    """Путь кандидата: тест на заявленный грейд → при неудаче ниже → при уверенном успехе одна попытка выше.

    pool=True — ответы предыдущих попыток онбординга учитываются в следующей (CatPlan.carry);
    по результатам валидации выигрыша в точности это не дало, по умолчанию выключено.
    """
    cat = get_catalog()
    g = cat.grade_index(cand.claimed_grade)
    logs: list[AttemptLog] = []

    def carry():
        return [r for l in logs for r in l.responses] if pool else []

    while True:
        log = simulate_attempt(cand, cat.grades[g].id, truth, rng, carry=carry(), **kw)
        logs.append(log)
        if log.result.decision == "confirmed":
            final, theta = g, log.result.theta
            if log.result.suggestion == "upgrade":
                up = simulate_attempt(
                    cand, cat.grades[g + 1].id, truth, rng, carry=carry(), kind="upgrade", **kw
                )
                logs.append(up)
                if up.result.decision == "confirmed":
                    final, theta = g + 1, up.result.theta
            return OnboardingResult(
                cat.grades[final].id, theta, len(logs), sum(len(l.responses) for l in logs), logs
            )
        if g == 0:
            return OnboardingResult(
                None, log.result.theta, len(logs), sum(len(l.responses) for l in logs), logs
            )
        g -= 1


def cohen_kappa(a: Sequence[int], b: Sequence[int], k: int, weighted: bool = False) -> float:
    m = np.zeros((k, k))
    for x, y in zip(a, b):
        m[x, y] += 1
    n = m.sum()
    if n == 0:
        return float("nan")
    w = np.array(
        [[((i - j) ** 2) / ((k - 1) ** 2) if weighted else float(i != j) for j in range(k)] for i in range(k)]
    )
    exp = np.outer(m.sum(1), m.sum(0)) / n
    return float(1 - (w * m).sum() / max((w * exp).sum(), 1e-12))


def grade_idx(g: str | None) -> int:
    """Индекс грейда; «не подтверждён ни один» сводим к Intern для матриц."""
    return get_catalog().grade_index(g) if g else 0


def run_reliability(cands: Sequence[TrueCandidate], truth: TrueBank, seed: int = 1, **kw) -> dict:
    cat = get_catalog()
    k = len(cat.grades)
    rng1, rng2 = random.Random(seed), random.Random(seed + 1000)
    first, second, true_g = [], [], []
    th1, th2, th_true = [], [], []
    items, attempts = [], []
    border = []  # |θ − ближайший порог| < 0.25 — самые сложные для классификации
    decisions1, decisions2 = [], []
    for c in cands:
        r1 = simulate_onboarding(c, truth, rng1, **kw)
        r2 = simulate_onboarding(c, truth, rng2, **kw)
        first.append(grade_idx(r1.grade))
        second.append(grade_idx(r2.grade))
        true_g.append(cat.grade_index(c.grade))
        th_true.append(c.theta)
        th1.append(r1.theta)
        th2.append(r2.theta)
        items.append(r1.items)
        attempts.append(r1.attempts)
        border.append(min(abs(c.theta - g.cut) for g in cat.grades[1:]) < 0.25)
        decisions1.append(r1.logs[0].result.decision)
        decisions2.append(r2.logs[0].result.decision)
    first_a, second_a, true_a = map(np.array, (first, second, true_g))
    border_a = np.array(border)
    confusion = np.zeros((k, k), dtype=int)
    for t, a in zip(true_g, first):
        confusion[t, a] += 1
    retest = np.zeros((k, k), dtype=int)
    for a, b in zip(first, second):
        retest[a, b] += 1
    return {
        "n": len(cands),
        "retest_agreement": float(np.mean(first_a == second_a)),
        "retest_kappa": cohen_kappa(first, second, k),
        "retest_kappa_weighted": cohen_kappa(first, second, k, weighted=True),
        "retest_theta_r": float(np.corrcoef(th1, th2)[0, 1]),
        "first_decision_agreement": float(np.mean(np.array(decisions1) == np.array(decisions2))),
        "accuracy_exact": float(np.mean(first_a == true_a)),
        "accuracy_within1": float(np.mean(np.abs(first_a - true_a) <= 1)),
        "accuracy_border": float(np.mean(first_a[border_a] == true_a[border_a]))
        if border_a.any()
        else float("nan"),
        "accuracy_nonborder": float(np.mean(first_a[~border_a] == true_a[~border_a])),
        "share_border": float(border_a.mean()),
        "overgrade_rate": float(np.mean(first_a > true_a)),
        "undergrade_rate": float(np.mean(first_a < true_a)),
        "theta_true_r": float(np.corrcoef(th_true, th1)[0, 1]),
        "kappa_vs_truth": cohen_kappa(true_g, first, k),
        "items_mean": float(np.mean(items)),
        "items_per_attempt": float(np.sum(items) / np.sum(attempts)),
        "attempts_mean": float(np.mean(attempts)),
        "confusion": confusion.tolist(),
        "retest_matrix": retest.tolist(),
    }


# ----------------------------------------------------------------------------------- утечки


def _fixed_form(spec: str, grade: str, length: int = 20) -> list[Family]:
    """Классический фиксированный тест: лучшие по информации в пороге задания с соблюдением blueprint."""
    cat = get_catalog()
    bp = cat.blueprint(spec, None)
    cut = cat.grade(grade).cut
    quotas = {s: max(1, round(w * length)) for s, w in bp.items()}
    form: list[Family] = []
    for s, q in quotas.items():
        fams = sorted(
            (f for f in REGISTRY.values() if f.skill == s),
            key=lambda f: -float(information(cut, f.a, f.b, f.c)),
        )
        form += fams[:q]
    return form[:length]


def run_leak_experiment(
    cands: Sequence[TrueCandidate], truth: TrueBank, shares=(0.0, 0.1, 0.25, 0.5, 0.75, 1.0), seed: int = 5
) -> dict:
    """Кандидаты пытаются подтвердить грейд на ступень выше истинного, имея доступ к утечкам.

    * fixed — единый фиксированный тест; утёкшие задания решаются (p = 0.98).
    * pool — адаптивный тест из банка *фиксированных* заданий (без параметризации): утёкшее
      задание узнаётся и решается (p = 0.98).
    * ours — параметризованные семейства: ответ утёкшего экземпляра не подходит к новому;
      знакомство с шаблоном даёт лишь частичный выигрыш p' = p + (1 − p)·0.25.
    Метрика — доля ложных подтверждений (грейд выше истинного подтверждён).
    """
    cat = get_catalog()
    cheaters = [c for c in cands if cat.grade_index(c.grade) < len(cat.grades) - 1 and c.search_status != "x"]
    out: dict[str, dict[str, float]] = {"fixed": {}, "pool": {}, "ours": {}}
    theta_infl: dict[str, dict[str, float]] = {"fixed": {}, "pool": {}, "ours": {}}
    for share in shares:
        rng_leak = random.Random(seed + int(share * 100))
        leaked = {fid for fid in sorted(REGISTRY) if rng_leak.random() < share}
        for system in ("fixed", "pool", "ours"):
            rng = random.Random(seed)
            fp = 0
            infl = []
            for c in cheaters:
                target = cat.grades[cat.grade_index(c.grade) + 1].id
                if system == "ours":

                    def leak(f, p, leaked=leaked):
                        return p + (1 - p) * 0.25 if f.id in leaked else p
                else:

                    def leak(f, p, leaked=leaked):
                        return 0.98 if f.id in leaked else p

                form = _fixed_form(c.spec, target) if system == "fixed" else None
                log = simulate_attempt(c, target, truth, rng, leak=leak, fixed_form=form)
                fp += log.result.decision == "confirmed"
                infl.append(log.result.theta - c.theta)
            out[system][f"{share:.2f}"] = fp / len(cheaters)
            theta_infl[system][f"{share:.2f}"] = float(np.mean(infl))
    return {"false_pass": out, "theta_inflation": theta_infl, "n_cheaters": len(cheaters)}


# ---------------------------------------------------------------------- дискриминативность и калибровка


def collect_responses(cands: Sequence[TrueCandidate], truth: TrueBank, seed: int = 9):
    rng = random.Random(seed)
    person, item_ids, correct, thetas = [], [], [], []
    for i, c in enumerate(cands):
        log = simulate_attempt(c, c.claimed_grade, truth, rng)
        for r in log.responses:
            person.append(i)
            item_ids.append(r.family_id)
            correct.append(r.correct)
        thetas.append(c.theta)
    return person, item_ids, correct, thetas


def run_discrimination(person, item_ids, correct, thetas) -> dict:
    by_item: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for p, it, x in zip(person, item_ids, correct):
        by_item[it].append((thetas[p], x))
    rpb = {}
    for it, rows in by_item.items():
        if len(rows) < 30:
            continue
        th = np.array([r[0] for r in rows])
        x = np.array([r[1] for r in rows], dtype=float)
        if x.std() == 0 or th.std() == 0:
            continue
        rpb[it] = float(np.corrcoef(th, x)[0, 1])
    vals = np.array(list(rpb.values()))
    exposure = Counter(item_ids)
    n_persons = len(set(person))
    exp_rates = np.array([v / n_persons for v in exposure.values()])
    return {
        "families_used": len(exposure),
        "families_total": len(REGISTRY),
        "families_evaluated": len(rpb),
        "rpb_median": float(np.median(vals)) if len(vals) else float("nan"),
        "rpb_share_below_0_2": float(np.mean(vals < 0.2)) if len(vals) else float("nan"),
        "weak_families": sorted([k for k, v in rpb.items() if v < 0.2]),
        "exposure_max": float(exp_rates.max()),
        "exposure_median": float(np.median(exp_rates)),
        "rpb": rpb,
    }


def run_recalibration(person, item_ids, correct, truth: TrueBank) -> dict:
    ids = sorted(set(item_ids))
    index = {fid: j for j, fid in enumerate(ids)}
    priors = [REGISTRY[fid].params for fid in ids]
    est = calibrate(person, [index[i] for i in item_ids], correct, priors)
    counts = Counter(item_ids)
    mask = [counts[fid] >= 30 for fid in ids]
    err_nom = [abs(REGISTRY[fid].b - truth.params[fid].b) for fid, m in zip(ids, mask) if m]
    err_est = [abs(e.b - truth.params[fid].b) for fid, e, m in zip(ids, est, mask) if m]
    return {
        "families": int(sum(mask)),
        "mae_b_nominal": float(np.mean(err_nom)) if err_nom else float("nan"),
        "mae_b_recalibrated": float(np.mean(err_est)) if err_est else float("nan"),
        "responses": len(correct),
    }


def run_drift(
    seed: int = 13,
    n_families: int = 60,
    n_responses: int = 600,
    leak_at: int = 200,
    affected: float = 0.5,
    cfg: CusumConfig = CusumConfig(),
) -> dict:
    """Детекция утечки CUSUM: доля ложных тревог на «честных» семействах и задержка обнаружения на утёкших."""
    rng = np.random.default_rng(seed)
    false_alarms = 0
    delays = []
    detected = 0
    for _ in range(n_families):
        p = rng.uniform(0.25, 0.8, n_responses)
        honest = [(float(pi), bool(rng.random() < pi)) for pi in p]
        if run_cusum(honest, cfg).flagged_at is not None:
            false_alarms += 1
        leaked = []
        for t, pi in enumerate(p):
            q = pi
            if t >= leak_at and rng.random() < affected:
                q = pi + (1 - pi) * 0.7
            leaked.append((float(pi), bool(rng.random() < q)))
        st = run_cusum(leaked, cfg)
        if st.flagged_at is not None and st.flagged_at > leak_at:
            detected += 1
            delays.append(st.flagged_at - leak_at)
    return {
        "families": n_families,
        "responses_per_family": n_responses,
        "false_alarm_rate": false_alarms / n_families,
        "detection_rate": detected / n_families,
        "delay_median": float(np.median(delays)) if delays else float("nan"),
        "delay_p90": float(np.percentile(delays, 90)) if delays else float("nan"),
        "affected_share": affected,
    }


def run_threshold_roc(
    cands: Sequence[TrueCandidate],
    truth: TrueBank,
    thresholds=(0.5, 0.6, 0.7, 0.75, 0.8),
    seed: int = 31,
    n: int = 500,
) -> dict:
    """Компромисс порога решения: ложные подтверждения при заявке на ступень выше истинной
    против верных подтверждений при честной заявке."""
    cat = get_catalog()
    up = [c for c in cands if cat.grade_index(c.grade) < len(cat.grades) - 1][:n]
    honest = list(cands[:n])
    out = {}
    for t in thresholds:
        cfg = replace(DEFAULT_CONFIG, pass_probability=t)
        rng = random.Random(seed)
        fp = np.mean(
            [
                simulate_attempt(
                    c, cat.grades[cat.grade_index(c.grade) + 1].id, truth, rng, config=cfg
                ).result.decision
                == "confirmed"
                for c in up
            ]
        )
        tp = np.mean(
            [
                simulate_attempt(c, c.grade, truth, rng, config=cfg).result.decision == "confirmed"
                for c in honest
            ]
        )
        out[f"{t:.2f}"] = {"false_pass_plus1": float(fp), "true_pass": float(tp)}
    return out
