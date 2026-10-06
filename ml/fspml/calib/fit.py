"""Калибровка параметров семейств по ответам панели LLM-респондентов и отчёт.

* Задание IRT = семейство (экземпляры одного семейства изоморфны, ответы объединяются).
* MML-EM (`assessment.calibration`) с экспертными параметрами как приором; c фиксирован форматом.
* Шкала: способности панели нормируются N(0, 1) — это шкала «популяции моделей», а не кандидатов.
  Поэтому калиброванные b переводятся на экспертную шкалу линейным связыванием (mean–sigma):
  сохраняется *порядок и относительные расстояния* сложностей, измеренные по данным.
* Проверки здравого смысла: способность респондента должна расти с размером модели и с
  включённым рассуждением; доля верных ответов должна падать с экспертным уровнем.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from ..assessment.bank import REGISTRY
from ..assessment.calibration import CalibrationConfig, calibrate
from ..assessment.irt import ItemParams
from ..catalog import DATA_DIR
from .respondents import CALIB_DIR

REPORT = Path(__file__).resolve().parents[3] / "docs" / "calib-results.md"
PARAMS_OUT = DATA_DIR / "calibrated_params.json"


def _load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def fit(path: Path = CALIB_DIR / "responses.jsonl") -> dict:
    rows = _load(path)
    fams = sorted({r["family"] for r in rows})
    persons = sorted({r["respondent"] for r in rows})
    fi = {f: i for i, f in enumerate(fams)}
    pi = {p: i for i, p in enumerate(persons)}
    priors = [REGISTRY[f].params for f in fams]
    cfg = CalibrationConfig(n_iter=60, prior_b_sd=1.5, prior_log_a_sd=0.5, min_responses=20)
    est = calibrate(
        [pi[r["respondent"]] for r in rows],
        [fi[r["family"]] for r in rows],
        [r["correct"] for r in rows],
        priors,
        cfg,
    )

    b_exp = np.array([p.b for p in priors])
    b_raw = np.array([p.b for p in est])
    # mean–sigma: шкала популяции моделей → экспертная шкала
    b_link = b_exp.mean() + b_exp.std() * (b_raw - b_raw.mean()) / max(b_raw.std(), 1e-9)
    levels = np.array([REGISTRY[f].level for f in fams])

    by_fam = defaultdict(list)
    by_person = defaultdict(list)
    for r in rows:
        by_fam[r["family"]].append(r["correct"])
        by_person[r["respondent"]].append(r["correct"])
    p_correct = np.array([np.mean(by_fam[f]) for f in fams])

    # способность респондента: EAP по калиброванным параметрам (для проверки порядка моделей)
    grid = np.linspace(-4, 4, 161)
    ability = {}
    for p in persons:
        lp = -0.5 * grid**2
        for r in rows:
            if r["respondent"] != p:
                continue
            it = est[fi[r["family"]]]
            pr = np.clip(it.c + (1 - it.c) / (1 + np.exp(-it.a * (grid - it.b))), 1e-9, 1 - 1e-9)
            lp = lp + (np.log(pr) if r["correct"] else np.log1p(-pr))
        w = np.exp(lp - lp.max())
        ability[p] = float((grid * w).sum() / w.sum())

    families = []
    for j, f in enumerate(fams):
        families.append(
            {
                "family": f,
                "skill": REGISTRY[f].skill,
                "level": int(levels[j]),
                "b_expert": float(b_exp[j]),
                "b_llm": float(b_link[j]),
                "a_llm": float(est[j].a),
                "c": float(est[j].c),
                "p_correct": float(p_correct[j]),
                "n": len(by_fam[f]),
                "flag_low_a": bool(est[j].a < 0.6),
                "flag_level": bool(abs(b_link[j] - b_exp[j]) > 1.0),
            }
        )
    by_model = defaultdict(list)
    for p, v in ability.items():
        key = p.split("-t")[0]  # модель + режим рассуждения
        by_model[key].append(v)
    res = {
        "n_responses": len(rows),
        "n_families": len(fams),
        "n_respondents": len(persons),
        "parsed_share": float(np.mean([r["parsed"] for r in rows])),
        "spearman_level_vs_b_llm": float(spearmanr(levels, b_link).statistic),
        "spearman_level_vs_p_correct": float(spearmanr(levels, p_correct).statistic),
        "p_correct_by_level": {int(lv): float(p_correct[levels == lv].mean()) for lv in sorted(set(levels))},
        "ability_by_model": {
            k: float(np.mean(v)) for k, v in sorted(by_model.items(), key=lambda kv: np.mean(kv[1]))
        },
        "accuracy_by_model": {
            k: float(np.mean([x for p, xs in by_person.items() if p.split("-t")[0] == k for x in xs]))
            for k in by_model
        },
        "families": families,
    }
    PARAMS_OUT.write_text(
        json.dumps(
            {
                f["family"]: {"a": round(f["a_llm"], 3), "b": round(f["b_llm"], 3), "c": f["c"]}
                for f in families
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    REPORT.write_text(report(res), encoding="utf-8")
    return res


def report(res: dict) -> str:
    fam = res["families"]
    low_a = [f for f in fam if f["flag_low_a"]]
    lvl = [f for f in fam if f["flag_level"]]
    L = [
        "# Калибровка банка заданий на панели LLM-респондентов",
        "",
        "> Сгенерировано `python -m fspml.calib fit`. Методика — [assessment.md](assessment.md).",
        "",
        f"Ответов: {res['n_responses']}; семейств: {res['n_families']}; респондентов: {res['n_respondents']}; "
        f"разобрано ответов: {res['parsed_share']:.0%}.",
        "",
        "## Проверка панели: сила растёт с размером модели",
        "",
        "| Респондент | Способность θ | Доля верных |",
        "|---|---|---|",
    ]
    for k, v in res["ability_by_model"].items():
        L.append(f"| {k} | {v:+.2f} | {res['accuracy_by_model'][k]:.0%} |")
    L += [
        "",
        "## Согласие экспертных уровней с измеренной сложностью",
        "",
        f"- Спирмен «экспертный уровень ↔ измеренная b»: **{res['spearman_level_vs_b_llm']:.2f}**",
        f"- Спирмен «уровень ↔ доля верных»: **{res['spearman_level_vs_p_correct']:.2f}** (ожидается отрицательная)",
        "",
        "| Уровень | Доля верных у панели |",
        "|---|---|",
        *[f"| {k} | {v:.0%} |" for k, v in res["p_correct_by_level"].items()],
        "",
        f"## Семейства с низкой различающей силой (a < 0.6): {len(low_a)}",
        "",
        "| Семейство | Навык | Уровень | a | Доля верных |",
        "|---|---|---|---|---|",
        *[
            f"| {f['family']} | {f['skill']} | {f['level']} | {f['a_llm']:.2f} | {f['p_correct']:.0%} |"
            for f in sorted(low_a, key=lambda f: f["a_llm"])
        ],
        "",
        f"## Семейства, где измеренная сложность расходится с экспертной больше чем на 1.0: {len(lvl)}",
        "",
        "| Семейство | Навык | Уровень | b эксперт | b измерено | Доля верных |",
        "|---|---|---|---|---|---|",
        *[
            f"| {f['family']} | {f['skill']} | {f['level']} | {f['b_expert']:+.2f} | {f['b_llm']:+.2f} | {f['p_correct']:.0%} |"
            for f in sorted(lvl, key=lambda f: f["b_llm"] - f["b_expert"])
        ],
        "",
        "## Ограничения",
        "",
        "- Модели — не люди: им легче задачи на знание и труднее точное пошаговое исполнение кода.",
        "  Поэтому измеренные параметры используются как *приор*, уточняемый ответами кандидатов",
        "  (онлайн MML-EM), а расхождения с экспертом — как список семейств на ревизию.",
        "- Шкала связана с экспертной линейно (mean–sigma): сохраняется порядок и относительные",
        "  расстояния сложностей, абсолютная привязка к порогам грейдов остаётся экспертной.",
    ]
    return "\n".join(L) + "\n"
