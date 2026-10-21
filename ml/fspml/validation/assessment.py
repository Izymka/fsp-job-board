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

import hashlib
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from ..assessment.bank import REGISTRY
from ..assessment.blueprint import personal_blueprint
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
    with_fsp_prior,
)
from ..assessment.drift import CusumConfig, run_cusum
from ..assessment.irt import ItemParams, information, prob
from ..assessment.items import Family
from ..catalog import get_catalog
from ..matching.scoring import fsp_strength
from ..nlp.skills import get_dictionary
from .population import TODAY, TrueCandidate, legacy_blueprint


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


def skill_ability(cand: TrueCandidate, skill: str) -> float:
    """Способность кандидата в навыке. Навыки вне прежнего состава теста получают такое же
    индивидуальное отклонение N(0, 0.45), детерминированное по (кандидат, навык), — иначе
    навыки, которых не было в генераторе, отвечались бы ровно по общему θ."""
    if skill in cand.skill_theta:
        return cand.skill_theta[skill]
    h = int(hashlib.sha1(f"{cand.id}|{skill}".encode()).hexdigest()[:12], 16)
    return cand.theta + random.Random(h).gauss(0, 0.45)


def _practiced_skills(cand: TrueCandidate) -> set[str]:
    """Навыки теста, которые подтверждает *реальный* стек кандидата (без накрутки)."""
    dic = get_dictionary()
    return {s for t in cand.techs if t in dic.techs for s in dic.techs[t].assess}


# Модель утечки: функция (семейство, вероятность верного) → новая вероятность
LeakFn = Callable[[Family, float], float]


@dataclass
class AttemptLog:
    result: CatResult
    responses: list[Response]
    true_correct_p: list[float] = field(default_factory=list)


def candidate_blueprint(cand: TrueCandidate, legacy: bool = False) -> dict[str, float]:
    """Состав теста кандидата так, как его строит продукт: ядро + модули по *заявленному* стеку
    (с накруткой — тест проверяет заявленное). legacy — прежний общий состав специализации."""
    if legacy:
        return legacy_blueprint(cand.spec, [cand.lang] if cand.lang else None)
    measurable = {s for s, n in Counter(f.skill for f in REGISTRY.values()).items() if n >= 2}
    return personal_blueprint(cand.spec, sorted(cand.claimed), available=measurable).weights


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
    seen: Iterable[str] = (),
    kind: str = "initial",
    legacy: bool = False,
    off_stack_penalty: float = 0.0,
) -> AttemptLog:
    """off_stack_penalty — насколько ниже общего уровня способность кандидата в навыке-модуле,
    которого нет в его реальном стеке (Python у Java-разработчика). Ядро специализации штрафом
    не затрагивается: это фундамент, которым владеют все в профессии."""
    cat = get_catalog()
    bank = bank if bank is not None else list(REGISTRY.values())
    if legacy:  # прежний алгоритм целиком: и состав, и остановка без требования покрытия
        config = replace(config, cover_min_items=0)
    plan = CatPlan(candidate_blueprint(cand, legacy), grade, config, kind, tuple(carry), seen=frozenset(seen))
    practiced = _practiced_skills(cand) if off_stack_penalty else set()
    core = set(cat.specializations[cand.spec].core)
    responses: list[Response] = []
    ps: list[float] = []
    form_iter = iter(fixed_form) if fixed_form is not None else None
    while True:
        if form_iter is not None:
            fam = next(form_iter, None)
        else:
            if should_stop(responses, plan, catalog=cat, bank=bank):
                break
            fam = select_next(responses, bank, plan, rng, catalog=cat)
        if fam is None:
            break
        tp = truth.params[fam.id]
        b_inst = tp.b + rng.gauss(0, truth.inst_sd)
        th = skill_ability(cand, fam.skill)
        if off_stack_penalty and fam.skill not in core and fam.skill not in practiced:
            th -= off_stack_penalty
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

    @property
    def families(self) -> set[str]:
        return {r.family_id for lg in self.logs for r in lg.responses}


def _keys(family_ids: Iterable[str]) -> set[str]:
    """Единицы неповторяемости (группа или семейство) — то, что кандидат воспринимает как «тот же вопрос»."""
    return {REGISTRY[f].content_key if f in REGISTRY else f for f in family_ids}


def repeat_share(later: Iterable[str], earlier: Iterable[str]) -> float:
    """Доля заданий более поздней попытки, уже встречавшихся (по группе/семейству) раньше."""
    later = list(later)
    if not later:
        return 0.0
    seen = _keys(earlier)
    return sum(1 for f in later if _keys([f]) <= seen) / len(later)


def simulate_onboarding(
    cand: TrueCandidate,
    truth: TrueBank,
    rng: random.Random,
    *,
    pool: bool = False,
    seen: Iterable[str] = (),
    avoid_seen: bool = True,
    **kw,
) -> OnboardingResult:
    """Путь кандидата: тест на заявленный грейд → при неудаче ниже → при уверенном успехе одна попытка выше.

    pool=True — ответы предыдущих попыток онбординга учитываются в следующей (CatPlan.carry);
    по результатам валидации выигрыша в точности это не дало, по умолчанию выключено.
    seen — семейства прошлых попыток кандидата (до этого онбординга); avoid_seen=True — как в
    продукте: увиденные семейства выбираются в последнюю очередь, в том числе внутри онбординга.
    """
    cat = get_catalog()
    g = cat.grade_index(cand.claimed_grade)
    logs: list[AttemptLog] = []
    before = set(seen)
    # как в продукте: достижения ФСП из реестра сдвигают приор θ всех попыток онбординга
    kw["config"] = with_fsp_prior(kw.get("config", DEFAULT_CONFIG), fsp_strength(cand.fsp, cand.spec, TODAY))

    def carry():
        return [r for l in logs for r in l.responses] if pool else []

    def seen_now():
        if not avoid_seen:
            return ()
        return before | {r.family_id for l in logs for r in l.responses}

    while True:
        log = simulate_attempt(cand, cat.grades[g].id, truth, rng, carry=carry(), seen=seen_now(), **kw)
        logs.append(log)
        if log.result.decision == "confirmed":
            final, theta = g, log.result.theta
            if log.result.suggestion == "upgrade":
                up = simulate_attempt(
                    cand,
                    cat.grades[g + 1].id,
                    truth,
                    rng,
                    carry=carry(),
                    seen=seen_now(),
                    kind="upgrade",
                    **kw,
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


def candidate_rng(seed: int, i: int) -> random.Random:
    """Свой поток случайных чисел у каждого кандидата: варианты настройки сравниваются на одних и
    тех же случайных числах, а изменённый путь одного кандидата не сдвигает случайные числа следующих
    (с общим потоком любое изменение «перетасовывает» всю популяцию, и разница вариантов тонет в шуме)."""
    return random.Random(seed * 100_003 + i)


def run_reliability(
    cands: Sequence[TrueCandidate], truth: TrueBank, seed: int = 1, avoid_seen: bool = True, **kw
) -> dict:
    """Повторное прохождение (ретест) — второй онбординг того же кандидата; при avoid_seen он знает
    семейства первого и идёт на параллельной форме, как в продукте."""
    cat = get_catalog()
    k = len(cat.grades)
    first, second, true_g = [], [], []
    th1, th2, th_true = [], [], []
    items, attempts = [], []
    border = []  # |θ − ближайший порог| < 0.25 — самые сложные для классификации
    decisions1, decisions2 = [], []
    rep_retest, rep_onboarding = [], []
    for i, c in enumerate(cands):
        r1 = simulate_onboarding(c, truth, candidate_rng(seed, i), avoid_seen=avoid_seen, **kw)
        r2 = simulate_onboarding(
            c,
            truth,
            candidate_rng(seed + 1000, i),
            seen=r1.families if avoid_seen else (),
            avoid_seen=avoid_seen,
            **kw,
        )
        rep_retest.append(repeat_share([r.family_id for lg in r2.logs for r in lg.responses], r1.families))
        for i in range(1, len(r1.logs)):
            prev = {r.family_id for lg in r1.logs[:i] for r in lg.responses}
            rep_onboarding.append(repeat_share([r.family_id for r in r1.logs[i].responses], prev))
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
    has_fsp = np.array([bool(c.fsp) for c in cands])
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
        "accuracy_fsp": float(np.mean(first_a[has_fsp] == true_a[has_fsp]))
        if has_fsp.any()
        else float("nan"),
        "accuracy_no_fsp": float(np.mean(first_a[~has_fsp] == true_a[~has_fsp])),
        "theta_true_r": float(np.corrcoef(th_true, th1)[0, 1]),
        "kappa_vs_truth": cohen_kappa(true_g, first, k),
        "items_mean": float(np.mean(items)),
        "items_per_attempt": float(np.sum(items) / np.sum(attempts)),
        "attempts_mean": float(np.mean(attempts)),
        # доля заданий, повторяющих по сути уже виденные: на ретесте и во 2-й+ попытке онбординга
        "repeat_retest": float(np.mean(rep_retest)),
        "repeat_onboarding": float(np.mean(rep_onboarding)) if rep_onboarding else float("nan"),
        "confusion": confusion.tolist(),
        "retest_matrix": retest.tolist(),
    }


REPORT_SEEDS = (1, 2, 3, 4, 5)
# Настройки выбираются на других сидах, чем публикуются: иначе выбор подгоняется под отчётный поток.
SELECTION_SEEDS = (101, 102, 103, 104, 105)


def _reliability_at(seed: int, cands, truth, kw: dict) -> dict:
    return run_reliability(cands, truth, seed=seed, **kw)


def run_multi_seed(
    cands: Sequence[TrueCandidate],
    truth: TrueBank,
    seeds: Sequence[int] = REPORT_SEEDS,
    workers: int | None = None,
    **kw,
) -> dict:
    """run_reliability на нескольких сидах: по скалярным метрикам — среднее, min и max; матрицы —
    по первому сиду. При 1000 кандидатах разброс точности между сидами — около ±1.5 п.п., поэтому
    варианты сравниваются по среднему, а не по одному прогону. Сиды считаются параллельно
    (workers=1 — последовательно)."""
    import os
    from concurrent.futures import ProcessPoolExecutor
    from functools import partial

    job = partial(_reliability_at, cands=cands, truth=truth, kw=kw)
    workers = workers if workers is not None else min(len(seeds), max(1, (os.cpu_count() or 2) - 1))
    if workers <= 1 or len(seeds) == 1:
        runs = [job(s) for s in seeds]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            runs = list(ex.map(job, seeds))
    out: dict = {"seeds": list(seeds)}
    for key, v in runs[0].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals = [r[key] for r in runs]
            out[key] = float(np.mean(vals))
            out[f"{key}_min"], out[f"{key}_max"] = float(np.min(vals)), float(np.max(vals))
        else:
            out[key] = v
    return out


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
    thresholds=(0.5, 0.6, 0.65, 0.7, 0.75, 0.8),
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


# ------------------------------------------------------------------------- состав теста


def run_blueprint_experiment(
    n: int = 600, seed: int = 41, penalties: Sequence[float] = (0.0, 0.5, 1.0)
) -> dict:
    """Прежний общий состав специализации против персонального (ядро + модули стека).

    Популяция — реалистичные стеки из архетипов, и backend-кандидат знает только свой язык
    (Java-разработчику Python не достаётся «в нагрузку»). off_stack_penalty — насколько ниже
    общего уровня способность в навыке-модуле не из реального стека: при 0 модель совпадает
    с остальной валидацией (стек не влияет на ответы), 0.5–1.0 — реалистичный диапазон (чужой
    язык или фреймворк знаком поверхностно).

    «Затронутые» кандидаты — те, у кого прежний состав содержит модули не из их реального стека
    (Python у Java-разработчика, React у Vue-разработчика, Kubernetes у Linux-администратора).
    """
    from .population import make_candidates

    cat = get_catalog()
    dic = get_dictionary()
    cands = make_candidates(n, seed=seed, stuffing_rate=0.3, realistic=True, force_language=False)
    truth = make_true_bank()

    def affected(c: TrueCandidate) -> bool:
        core = set(cat.specializations[c.spec].core)
        return any(s not in core and s not in _practiced_skills(c) for s in candidate_blueprint(c, True))

    aff = np.array([affected(c) for c in cands])
    true_g = np.array([cat.grade_index(c.grade) for c in cands])
    out: dict = {"n": n, "affected_share": float(aff.mean()), "arms": {}}
    for pen in penalties:
        for arm in ("legacy", "personal"):
            rng1, rng2 = random.Random(seed), random.Random(seed + 1000)
            first, second, bias, items, attempts = [], [], [], [], []
            claimed_tested, stuffed_conf, real_conf = [], [], []
            for c in cands:
                kw = {"legacy": arm == "legacy", "off_stack_penalty": pen}
                r1 = simulate_onboarding(c, truth, rng1, **kw)
                r2 = simulate_onboarding(c, truth, rng2, seen=r1.families, **kw)
                first.append(grade_idx(r1.grade))
                second.append(grade_idx(r2.grade))
                bias.append(r1.logs[0].result.theta - c.theta)
                items.append(sum(len(lg.responses) for lg in r1.logs))
                attempts.append(r1.attempts)
                st = r1.logs[-1].result.skills
                for t in c.claimed:
                    assess = dic.techs[t].assess if t in dic.techs else ()
                    statuses = [st[a].status for a in assess if a in st]
                    has = any(x != "no_data" for x in statuses)
                    if assess:
                        claimed_tested.append(has)
                    if has:
                        confirmed = all(x == "confirmed" for x in statuses if x != "no_data")
                        (stuffed_conf if t in c.stuffed else real_conf).append(confirmed)
            f, s2 = np.array(first), np.array(second)
            key = f"{arm}@{pen:.1f}"
            out["arms"][key] = {
                "accuracy_exact": float(np.mean(f == true_g)),
                "accuracy_affected": float(np.mean(f[aff] == true_g[aff])),
                "accuracy_unaffected": float(np.mean(f[~aff] == true_g[~aff])),
                "undergrade_affected": float(np.mean(f[aff] < true_g[aff])),
                "overgrade_rate": float(np.mean(f > true_g)),
                "retest_agreement": float(np.mean(f == s2)),
                "theta_bias_affected": float(np.mean(np.array(bias)[aff])),
                "theta_bias_unaffected": float(np.mean(np.array(bias)[~aff])),
                "items_per_attempt": float(np.sum(items) / np.sum(attempts)),
                "claimed_tested_share": float(np.mean(claimed_tested)) if claimed_tested else float("nan"),
                # среди технологий с данными теста: доля подтверждённых — накрученных и реальных
                "stuffed_confirmed_rate": float(np.mean(stuffed_conf)) if stuffed_conf else float("nan"),
                "real_confirmed_rate": float(np.mean(real_conf)) if real_conf else float("nan"),
            }
    return out
