"""Оценка систем подбора по трём независимым источникам эталона и проверка самих асессоров.

Источники эталона:
* `truth` — скрытая истина синтетической популяции (только синтетические потребности);
* `llm` — ансамбль LLM-асессоров по рубрике (все потребности, включая реальные вакансии);
* `human` — эксперты: используются для проверки LLM-асессора (согласие), а не для ранжирования
  систем — их меток мало для системных метрик.

LLM-метки допускаются к оценке систем, только если согласие LLM ↔ эксперты не хуже согласия
экспертов между собой (порог в отчёте).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import stats as st
from .build import BENCH_DIR, DATA, load_jsonl
from .judge import aggregate

RESULTS = BENCH_DIR / "results"
REPORT_MD = BENCH_DIR.parents[1] / "docs" / "bench-results.md"
BASELINE_ORDER = [
    "ours",
    "ours_v2",
    "ours_v3",
    "ours_v4",
    "ours_v5",
    "ours_v5_ce",
    "ours_v6",
    "ours_v7",
    "rerank_bge",
    "hybrid_rrf",
    "dense_frida",
    "dense_qwen3",
    "bm25",
    "test_only",
    "random",
]


def _system_metrics(runs: dict, qrels_by_need: dict[str, dict[str, int]], need_ids: list[str]) -> dict:
    out = {}
    per_need: dict[str, list[float]] = {}
    for sysname, run in runs.items():
        nd, pr, jd, used = [], [], [], []
        for nid in need_ids:
            q = qrels_by_need.get(nid)
            if not q:
                continue
            v = st.ndcg_condensed(run.get(nid, []), q)
            if v is None:
                continue
            nd.append(v)
            pr.append(st.precision_condensed(run.get(nid, []), q) or 0.0)
            jd.append(st.judged_at_k(run.get(nid, []), q))
            used.append(nid)
        if not nd:
            continue
        lo, hi = st.bootstrap_ci(nd)
        out[sysname] = {
            "ndcg@10": float(np.mean(nd)),
            "ndcg@10_ci": [lo, hi],
            "p@10": float(np.mean(pr)),
            "judged@10": float(np.mean(jd)),
            "n_needs": len(nd),
        }
        per_need[sysname] = dict(zip(used, nd))
    if "ours" in per_need:
        for sysname, vals in per_need.items():
            if sysname == "ours":
                continue
            common = [n for n in per_need["ours"] if n in vals]
            a = [per_need["ours"][n] for n in common]
            b = [vals[n] for n in common]
            out[sysname]["delta_vs_ours"] = float(np.mean(np.array(b) - np.array(a))) if common else None
            out[sysname]["p_value_vs_ours"] = st.randomization_test(a, b) if common else None
    return out


def _agreement(pairs_a: dict[str, int], pairs_b: dict[str, int]) -> dict:
    common = sorted(set(pairs_a) & set(pairs_b))
    if len(common) < 5:
        return {"n": len(common)}
    a = [pairs_a[p] for p in common]
    b = [pairs_b[p] for p in common]
    return {
        "n": len(common),
        "kappa_w": st.weighted_kappa(a, b),
        "kappa": st.kappa(a, b),
        "exact": float(np.mean(np.array(a) == np.array(b))),
        "within1": float(np.mean(np.abs(np.array(a) - np.array(b)) <= 1)),
        "spearman": st.spearman(a, b),
    }


def evaluate(data: Path = DATA, models: list[str] | None = None) -> dict:
    needs = {r["need_id"]: r for r in load_jsonl(data / "needs.jsonl")}
    cand_ids = [r["cand_id"] for r in load_jsonl(data / "candidates.jsonl")]
    pairs = load_jsonl(data / "pairs.jsonl")
    runs = json.loads((data / "runs.json").read_text(encoding="utf-8"))
    pid_to_pair = {p["pair_id"]: p for p in pairs}
    synthetic = [n for n, r in needs.items() if r["source"] == "synthetic"]
    vacancy = [n for n, r in needs.items() if r["source"] == "vacancy"]
    res: dict = {"n_needs": len(needs), "n_pairs": len(pairs), "systems": {}, "agreement": {}}

    # --- эталон 1: скрытая истина (полная разметка всех кандидатов) ---
    truth: dict[str, dict[str, int]] = defaultdict(dict)
    for r in load_jsonl(data / "truth.jsonl"):
        truth[r["need_id"]][r["cand_id"]] = r["rel"]
    truth_full = {n: {c: truth[n].get(c, 0) for c in cand_ids} for n in synthetic}
    res["systems"]["truth"] = _system_metrics(runs, truth_full, synthetic)
    truth_pairs = {
        p["pair_id"]: truth[p["need_id"]].get(p["cand_id"], 0) for p in pairs if p["need_id"] in truth_full
    }

    # --- эталон 2: LLM-асессоры (каждый судья — отдельно) ---
    llm_rows = load_jsonl(data / "judgments_llm.jsonl")
    need_size = Counter(p["need_id"] for p in pairs)
    all_models = sorted({r["model"] for r in llm_rows})
    per_model = {
        m: {r["pair_id"]: r["label"] for r in llm_rows if r["model"] == m and r["label"] is not None}
        for m in all_models
    }
    # по умолчанию — судьи, разметившие хотя бы четверть пула (пилот облачных моделей на 45 парах не в счёт)
    llm_models = models or [m for m in all_models if len(per_model[m]) >= 0.25 * len(pairs)]
    per_model = {m: per_model[m] for m in llm_models}
    llm = aggregate(llm_rows, llm_models)
    if llm:
        res["llm_models"] = llm_models
        res["judges"] = {}
        covered_by_all = set(needs)
        for m in llm_models:
            q: dict[str, dict[str, int]] = defaultdict(dict)
            for pid, lab in per_model[m].items():
                p = pid_to_pair[pid]
                q[p["need_id"]][p["cand_id"]] = lab
            # вакансия засчитывается судье, если он разметил ≥ 90% её пар (остальное — доразметка новых версий)
            full = [n for n in needs if len(q.get(n, {})) >= 0.9 * need_size[n]]
            covered_by_all &= set(full)
            res["judges"][m] = {
                "pairs": len(per_model[m]),
                "needs": len(full),
                "needs_vacancy": sum(n in vacancy for n in full),
                "systems": _system_metrics(runs, q, full),
                "systems_vacancy": _system_metrics(runs, q, [n for n in full if n in vacancy]),
                "qrels": q,
            }
        # сводка «все судьи на одних и тех же вакансиях»
        common = sorted(covered_by_all)
        res["common_needs"] = len(common)
        res["common"] = {m: _system_metrics(runs, j.pop("qrels"), common) for m, j in res["judges"].items()}
        res["common"]["truth"] = _system_metrics(runs, truth_full, [n for n in common if n in truth_full])
        res["agreement"]["judges_pairwise"] = {
            f"{a} ↔ {b}": _agreement(per_model[a], per_model[b])
            for i, a in enumerate(llm_models)
            for b in llm_models[i + 1 :]
        }
        res["agreement"]["llm_models_alpha"] = st.krippendorff_alpha_interval(
            {pid: {m: per_model[m][pid] for m in llm_models if pid in per_model[m]} for pid in llm}
        )
        res["agreement"]["llm_model_vs_truth"] = {
            m: _agreement(per_model[m], truth_pairs) for m in llm_models
        }
        res["agreement"]["controls_zero_share"] = {m: _controls(per_model[m], pairs) for m in llm_models}
        res["agreement"]["system_ranking_tau_vs_truth"] = {}
        t_sys = res["systems"]["truth"]
        for m in llm_models:
            q2: dict[str, dict[str, int]] = defaultdict(dict)
            for pid, lab in per_model[m].items():
                q2[pid_to_pair[pid]["need_id"]][pid_to_pair[pid]["cand_id"]] = lab
            l_sys = _system_metrics(
                runs, q2, [n for n in synthetic if len(q2.get(n, {})) >= 0.9 * need_size[n]]
            )
            both = [s for s in t_sys if s in l_sys]
            if len(both) >= 3:
                res["agreement"]["system_ranking_tau_vs_truth"][m] = st.kendall_tau(
                    [t_sys[s]["ndcg@10"] for s in both], [l_sys[s]["ndcg@10"] for s in both]
                )
        # Сколько релевантного системы упустили: доля релевантных среди случайных пар вне пула
        rnd = [llm[p["pair_id"]] for p in pairs if p["kind"] == "random" and p["pair_id"] in llm]
        res["pool_random_relevant_share"] = float(np.mean([x >= 2 for x in rnd])) if rnd else None

    # --- эталон 3: эксперты ---
    hum_rows = load_jsonl(data / "judgments_human.jsonl")
    if hum_rows:
        by_ann: dict[str, dict[str, int]] = defaultdict(dict)
        for r in hum_rows:
            by_ann[r["annotator"]][r["pair_id"]] = r["label"]
        anns = sorted(by_ann)
        units: dict[str, dict[str, int]] = defaultdict(dict)
        for a in anns:
            for pid, lab in by_ann[a].items():
                units[pid][a] = lab
        consensus = {pid: int(np.mean(list(v.values())) + 0.5) for pid, v in units.items()}
        ag = res["agreement"]
        ag["annotators"] = anns
        ag["human_alpha"] = st.krippendorff_alpha_interval(units) if len(anns) > 1 else None
        ag["human_pairwise"] = {
            f"{a}~{b}": _agreement(by_ann[a], by_ann[b]) for i, a in enumerate(anns) for b in anns[i + 1 :]
        }
        ag["human_vs_truth"] = _agreement(consensus, truth_pairs)
        ag["controls_zero_share_human"] = _controls(consensus, pairs)
        if llm:
            ag["llm_vs_human"] = _agreement(llm, consensus)
            ag["llm_model_vs_human"] = {m: _agreement(per_model[m], consensus) for m in llm_models}
            # LLM как «ещё один эксперт»: α группы экспертов с LLM и без него
            if len(anns) > 1:
                with_llm = {pid: {**v, "llm": llm[pid]} for pid, v in units.items() if pid in llm}
                ag["alpha_humans_plus_llm"] = st.krippendorff_alpha_interval(with_llm)

    # Проверка предвзятости асессора к нашей механике: смещение (метка − истина) на парах,
    # которые нашла только наша механика, против пар, найденных только бейзлайнами.
    if llm and truth_pairs:
        ours_top = {(n, c) for n, run in runs.get("ours", {}).items() for c in run[:10]}
        base_top = {
            (n, c)
            for s, r in runs.items()
            if not s.startswith("ours") and s not in ("random", "test_only")
            for n, run in r.items()
            for c in run[:10]
        }
        bias = {}
        for m in llm_models:
            lab = per_model[m]
            out = {}
            for name, sel in (
                ("ours_only", lambda k: k in ours_top and k not in base_top),
                ("baselines_only", lambda k: k in base_top and k not in ours_top),
            ):
                ids = [
                    pid
                    for pid in truth_pairs
                    if pid in lab and sel((pid_to_pair[pid]["need_id"], pid_to_pair[pid]["cand_id"]))
                ]
                out[name] = {
                    "n": len(ids),
                    "offset": float(np.mean([lab[p] - truth_pairs[p] for p in ids])) if ids else None,
                }
            bias[m] = out
        res["agreement"]["assessor_bias_vs_truth"] = bias

    return res


def _controls(labels: dict[str, int], pairs: list[dict]) -> float | None:
    vals = [labels[p["pair_id"]] == 0 for p in pairs if p["kind"] == "control" and p["pair_id"] in labels]
    return float(np.mean(vals)) if vals else None


# ------------------------------------------------------------------------------------- отчёт

TITLES = {
    "ours": "**Наша механика v1**",
    "ours_v2": "**Наша механика v2** (граф навыков, «ворота»)",
    "ours_v3": "**Наша механика v3** (LambdaMART, дистилляция)",
    "ours_v4": "**Наша механика v4** (гибрид v1 + кросс-энкодер)",
    "ours_v5": "**Наша механика v5** (специфичность требований + «ворота»)",
    "ours_v5_ce": "**Наша механика v5 + кросс-энкодер** (гибрид)",
    "ours_v6": "**Наша механика v6** (v5 + «ворота» основной технологии)",
    "ours_v7": "**Наша механика v7** (v6 + весомый ФСП, ФСП как опыт)",
    "rerank_bge": "Кросс-энкодер bge-reranker-v2-m3 (поверх гибрида)",
    "hybrid_rrf": "Гибрид BM25 + FRIDA (RRF)",
    "dense_frida": "Эмбеддинги FRIDA",
    "dense_qwen3": "Эмбеддинги Qwen3-Embedding-0.6B",
    "bm25": "BM25 по карточке",
    "test_only": "Только результат теста",
    "random": "Случайный порядок",
}


def _fmt(x, nd=3) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def report(res: dict, meta: dict) -> str:
    L = [
        "# Бенчмарк подбора: результаты слепой разметки",
        "",
        "> Сгенерировано `make bench-eval`. Методика — [bench.md](bench.md#методика).",
        "",
        f"Потребностей: {res['n_needs']} (синтетических {meta.get('n_synthetic')}, реальных описаний вакансий "
        f"{res['n_needs'] - meta.get('n_synthetic', 0)}); кандидатов: {meta.get('n_candidates')}; пар в пуле: {res['n_pairs']}.",
        "",
    ]

    def table(rows: dict, title: str, note: str = "") -> None:
        if not rows:
            return
        L.extend([f"### {title}", ""] + ([note, ""] if note else []))
        L.extend(
            [
                "| Система | nDCG@10 [95% ДИ] | P@10 | Размечено в top-10 | Δ к v1 | p |",
                "|---|---|---|---|---|---|",
            ]
        )
        for s in BASELINE_ORDER:
            if s in rows:
                r, ci = rows[s], rows[s]["ndcg@10_ci"]
                L.append(
                    f"| {TITLES.get(s, s)} | {_fmt(r['ndcg@10'])} [{_fmt(ci[0], 2)}–{_fmt(ci[1], 2)}] | "
                    f"{_fmt(r['p@10'])} | {_fmt(r['judged@10'], 2)} | {_fmt(r.get('delta_vs_ours'))} | "
                    f"{_fmt(r.get('p_value_vs_ours'), 4)} |"
                )
        L.append("")

    judges = res.get("judges", {})
    if res.get("common"):
        cols = list(res["common"])
        L += [
            f"## Сводка: все судьи на одних и тех же {res['common_needs']} вакансиях",
            "",
            "nDCG@10. Числа сравниваются только внутри столбца: у судей разная строгость шкалы.",
            "",
            "| Система | " + " | ".join("скрытая истина" if c == "truth" else c for c in cols) + " |",
            "|---|" + "---|" * len(cols),
        ]
        for s in BASELINE_ORDER:
            if all(s in res["common"][c] for c in cols):
                L.append(
                    f"| {TITLES.get(s, s)} | "
                    + " | ".join(_fmt(res["common"][c][s]["ndcg@10"]) for c in cols)
                    + " |"
                )
        L.append("")
    L += ["## Результаты по каждому судье", ""]
    table(res["systems"].get("truth"), "Скрытая истина (30 синтетических вакансий)")
    for m, j in judges.items():
        table(
            j["systems"],
            f"Судья {m}",
            f"Размечено пар: {j['pairs']}; вакансий целиком: {j['needs']} (из них живых: {j['needs_vacancy']}).",
        )
        if j["needs_vacancy"]:
            table(j["systems_vacancy"], f"Судья {m}: только живые описания вакансий ({j['needs_vacancy']})")
    ag = res.get("agreement", {})
    if ag:
        L += [
            "## Согласие асессоров",
            "",
            "| Сравнение | n | κ взв. | точное | ±1 | Спирмен |",
            "|---|---|---|---|---|---|",
        ]

        def row(name, a):
            if a and a.get("n", 0) >= 5:
                L.append(
                    f"| {name} | {a['n']} | {_fmt(a['kappa_w'], 2)} | {_fmt(a['exact'], 2)} | {_fmt(a['within1'], 2)} | {_fmt(a['spearman'], 2)} |"
                )

        for k, a in (ag.get("judges_pairwise") or {}).items():
            row(k, a)
        for k, a in (ag.get("human_pairwise") or {}).items():
            row(f"Эксперт ↔ эксперт ({k})", a)
        row("Судьи-LLM (среднее) ↔ эксперты", ag.get("llm_vs_human"))
        for m, a in (ag.get("llm_model_vs_human") or {}).items():
            row(f"{m} ↔ эксперты", a)
        for m, a in (ag.get("llm_model_vs_truth") or {}).items():
            row(f"{m} ↔ скрытая истина", a)
        row("Эксперты ↔ скрытая истина", ag.get("human_vs_truth"))
        L.append("")
        bias = ag.get("assessor_bias_vs_truth") or {}
        if bias:
            L += [
                "**Проверка предвзятости судьи** (средний сдвиг «оценка судьи − скрытая истина»). Если судья "
                "подыгрывает нашей механике, сдвиг на её находках будет больше, чем на находках бейзлайнов. "
                "Отрицательный сдвиг на находках механики у всех судей означает обратное: скрытая истина, "
                "построенная из тех же факторов, что и формула, сама немного завышает находки механики.",
                "",
                "| Асессор | Только наша механика: n / смещение | Только бейзлайны: n / смещение |",
                "|---|---|---|",
            ]
            for m, b in bias.items():
                o, bl = b["ours_only"], b["baselines_only"]
                L.append(f"| {m} | {o['n']} / {_fmt(o['offset'], 2)} | {bl['n']} / {_fmt(bl['offset'], 2)} |")
            L.append("")
        extra = [
            ("α Криппендорфа: судьи-LLM", ag.get("llm_models_alpha")),
            ("α Криппендорфа: эксперты", ag.get("human_alpha")),
            ("α Криппендорфа: эксперты + LLM", ag.get("alpha_humans_plus_llm")),
            *[
                (f"Контрольные пары, оценка 0 — {m}", v)
                for m, v in (ag.get("controls_zero_share") or {}).items()
            ],
            ("Контрольные пары, оценка 0 — эксперты", ag.get("controls_zero_share_human")),
            *[
                (f"τ Кендалла: рейтинг систем по истине и по {m}", v)
                for m, v in (ag.get("system_ranking_tau_vs_truth") or {}).items()
            ],
            ("Доля релевантных среди случайных пар вне пула", res.get("pool_random_relevant_share")),
        ]
        L += [f"- {k}: **{_fmt(v, 2)}**" for k, v in extra if v is not None]
        L.append("")
    return "\n".join(L)


def run(data: Path = DATA, out_md: Path | None = None, models: list[str] | None = None) -> dict:
    res = evaluate(data, models)
    meta = json.loads((data / "meta.json").read_text(encoding="utf-8"))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    md = report(res, meta)
    out_md = out_md or REPORT_MD
    out_md.write_text(md, encoding="utf-8")
    return res
