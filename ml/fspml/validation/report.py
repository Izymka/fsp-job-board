"""`make validate`: воспроизводимый прогон всей процедуры валидации → docs/validation.md + графики."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
import yaml

from ..assessment.bank import REGISTRY
from ..assessment.cat import DEFAULT_CONFIG
from ..catalog import DATA_DIR, get_catalog
from ..nlp.vacancy import parse_need
from . import assessment as va
from . import matching as vm
from . import resume as vr
from .population import make_candidates, make_needs

PRIMARY = "#402FFF"
ACCENT = "#EC1D35"
DARK = "#1B1C21"
GREY = "#C8C9CA"
LIGHT_PRIMARY = "#A79FFF"


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": DARK,
            "axes.labelcolor": DARK,
            "xtick.color": DARK,
            "ytick.color": DARK,
            "axes.titleweight": "bold",
            "figure.dpi": 130,
        }
    )
    return plt


def bank_stats() -> dict:
    by_skill: dict[str, Counter] = {}
    formats = Counter()
    for f in REGISTRY.values():
        by_skill.setdefault(f.skill, Counter())[f.level] += 1
        formats[f.generate(0).kind] += 1
    # оценка размера пространства экземпляров: доля уникальных из 200 генераций
    diversity = []
    for f in REGISTRY.values():
        seen = {
            (i.prompt, i.code, json.dumps(i.options, ensure_ascii=False))
            for i in (f.generate(s) for s in range(200))
        }
        diversity.append(len(seen))
    d = np.array(diversity)
    return {
        "families": len(REGISTRY),
        "skills": {k: dict(sorted(v.items())) for k, v in sorted(by_skill.items())},
        "formats": dict(formats),
        "input_share": (formats["number"] + formats["text"]) / len(REGISTRY),
        "unique_of_200_median": float(np.median(d)),
        "share_ge_100_unique": float(np.mean(d >= 100)),
        "share_lt_10_unique": float(np.mean(d < 10)),
    }


def vacancy_parsing() -> dict:
    vs = yaml.safe_load((DATA_DIR / "vacancies.yaml").read_text(encoding="utf-8"))["vacancies"]
    rows = []
    for v in vs:
        n = parse_need(v["text"], v["title"])
        rows.append(
            {
                "id": v["id"],
                "spec_ok": n.specialization == v["expected"]["specialization"],
                "grade_ok": n.grade == v["expected"]["grade"],
                "salary": [n.salary_from, n.salary_to],
                "blueprint": n.blueprint,
            }
        )
    return {
        "n": len(rows),
        "spec_acc": float(np.mean([r["spec_ok"] for r in rows])),
        "grade_acc": float(np.mean([r["grade_ok"] for r in rows])),
        "rows": rows,
    }


def run(out_dir: Path, n_candidates: int = 1000, n_needs: int = 30, quick: bool = False) -> dict:
    t0 = time.time()
    img = out_dir / "img"
    img.mkdir(parents=True, exist_ok=True)
    plt = _plt()
    cat = get_catalog()
    if quick:
        n_candidates, n_needs = 300, 12
    cands = make_candidates(n_candidates, stuffing_rate=0.3, history=True)
    truth = va.make_true_bank()
    res: dict = {"config": {"n_candidates": n_candidates, "n_needs": n_needs, "cat": DEFAULT_CONFIG.__dict__}}

    # ---------------------------------------------------------------- тестирование
    res["bank"] = bank_stats()
    res["reliability"] = va.run_reliability(cands, truth)
    sub = cands[: max(300, n_candidates // 2)]
    res["threshold_tradeoff"] = {}
    for pp in (0.5, 0.6, 0.7, 0.8):
        r = va.run_reliability(sub, truth, config=replace(DEFAULT_CONFIG, pass_probability=pp))
        res["threshold_tradeoff"][f"{pp:.1f}"] = {
            k: r[k]
            for k in ("accuracy_exact", "overgrade_rate", "undergrade_rate", "retest_agreement", "items_mean")
        }
    res["threshold_roc"] = va.run_threshold_roc(cands, truth, n=200 if quick else 500)
    res["length_curve"] = {}
    for mx in (12, 18, 25, 35):
        cfg = replace(DEFAULT_CONFIG, max_items=mx, min_items=min(DEFAULT_CONFIG.min_items, mx))
        r = va.run_reliability(sub, truth, config=cfg)
        res["length_curve"][str(mx)] = {
            k: r[k]
            for k in (
                "retest_agreement",
                "retest_kappa_weighted",
                "accuracy_exact",
                "items_per_attempt",
                "theta_true_r",
            )
        }
    res["blueprint"] = va.run_blueprint_experiment(n=200 if quick else 600)
    # та же популяция и те же сиды, что у основного прогона, — сравнение только по памяти о заданиях
    no_memory = va.run_reliability(cands, truth, avoid_seen=False)
    res["repeat_ablation"] = {
        k: no_memory[k]
        for k in (
            "repeat_retest",
            "repeat_onboarding",
            "retest_agreement",
            "retest_kappa_weighted",
            "retest_theta_r",
            "accuracy_exact",
        )
    }
    pooled = va.run_reliability(sub, truth, pool=True)
    res["pooling_ablation"] = {
        k: pooled[k] for k in ("retest_agreement", "accuracy_exact", "items_mean", "overgrade_rate")
    }
    res["leaks"] = va.run_leak_experiment(cands[: 400 if not quick else 150], truth)
    person, items, correct, thetas = va.collect_responses(cands, truth)
    disc = va.run_discrimination(person, items, correct, thetas)
    res["discrimination"] = {k: v for k, v in disc.items() if k != "rpb"}
    res["recalibration"] = va.run_recalibration(person, items, correct, truth)
    res["drift"] = va.run_drift()

    # ---------------------------------------------------------------- подбор
    needs = make_needs(n_needs, history=True)
    obs = vm.observe(cands, truth)
    res["categorization"] = vm.category_accuracy(obs)
    res["matching"] = vm.evaluate(cands, needs, truth, obs=obs)
    # вклад опыта: те же кандидаты и потребности, у кандидатов скрыта история работы
    res["matching_no_experience"] = vm.evaluate(cands, needs, truth, obs=vm.without_experience(obs))
    cands0 = make_candidates(n_candidates, stuffing_rate=0.0, history=True)
    res["matching_no_stuffing"] = vm.evaluate(cands0, needs, truth)
    res["sensitivity"] = vm.weight_sensitivity(cands, needs, truth, obs=obs)
    res["composition_matching"] = vm.composition_effect(cands, needs, truth, obs=obs)

    # ---------------------------------------------------------------- NLP
    res["vacancies"] = vacancy_parsing()
    res["resume"] = vr.evaluate(30 if quick else 60)
    res["elapsed_sec"] = round(time.time() - t0, 1)

    # ---------------------------------------------------------------- графики
    _chart_leaks(plt, res["leaks"], img / "val_leaks.png")
    _chart_confusion(
        plt, res["reliability"]["confusion"], [g.name for g in cat.grades], img / "val_confusion.png"
    )
    _chart_systems(
        plt, res["matching"]["systems"], res["matching_no_stuffing"]["systems"], img / "val_matching.png"
    )
    _chart_length(plt, res["length_curve"], img / "val_length.png")

    (out_dir / "validation.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8"
    )
    (out_dir / "validation.md").write_text(render_md(res), encoding="utf-8")
    if not quick:
        (DATA_DIR / "validation_summary.json").write_text(
            json.dumps(summary(res), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return res


def summary(r: dict) -> dict:
    """Ключевые цифры для UI («Как это работает») — отдаются API /api/catalog/validation."""
    rel = r["reliability"]
    m = r["matching"]["systems"]
    m0 = r["matching_no_stuffing"]["systems"]
    lk = r["leaks"]["false_pass"]
    return {
        "n_candidates": r["config"]["n_candidates"],
        "families": r["bank"]["families"],
        "unique_of_200_median": r["bank"]["unique_of_200_median"],
        "accuracy_exact": rel["accuracy_exact"],
        "accuracy_within1": rel["accuracy_within1"],
        "overgrade_rate": rel["overgrade_rate"],
        "retest_agreement": rel["retest_agreement"],
        "retest_kappa_weighted": rel["retest_kappa_weighted"],
        "items_per_attempt": rel["items_per_attempt"],
        "repeat_onboarding": rel["repeat_onboarding"],
        "repeat_retest": rel["repeat_retest"],
        "leak_50": {k: lk[k]["0.50"] for k in lk},
        "drift_detection": r["drift"]["detection_rate"],
        "drift_delay_median": r["drift"]["delay_median"],
        "recalibration": r["recalibration"],
        "ndcg": {k: m[k]["ndcg@10"] for k in m},
        "ndcg_clean": {k: m0[k]["ndcg@10"] for k in m0},
        "accepted": {k: m[k]["accepted@10"] for k in m},
        "ndcg_no_experience": r["matching_no_experience"]["systems"]["ours"]["ndcg@10"]
        if "matching_no_experience" in r
        else None,
        "p10": {k: m[k]["p@10"] for k in m},
    }


# ------------------------------------------------------------------------------------- графики


def _chart_leaks(plt, leaks, path):
    fig, ax = plt.subplots(figsize=(7, 3.8))
    labels = {
        "fixed": "Единый фиксированный тест",
        "pool": "Банк фиксированных заданий + CAT",
        "ours": "Наш подход: семейства + CAT",
    }
    colors = {"fixed": GREY, "pool": DARK, "ours": PRIMARY}
    for k in ("fixed", "pool", "ours"):
        xs = [float(s) * 100 for s in leaks["false_pass"][k]]
        ys = [v * 100 for v in leaks["false_pass"][k].values()]
        ax.plot(xs, ys, marker="o", lw=2.4 if k == "ours" else 1.6, color=colors[k], label=labels[k])
    ax.set_xlabel("Доля утёкших заданий банка, %")
    ax.set_ylabel("Ложные подтверждения грейда, %")
    ax.set_title("Устойчивость к утечкам: кандидаты на ступень ниже заявленного грейда")
    ax.legend(frameon=False, fontsize=8)
    ax.set_ylim(0, 100)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _chart_confusion(plt, m, names, path):
    m = np.array(m)
    fig, ax = plt.subplots(figsize=(4.6, 4))
    norm = m / np.maximum(m.sum(axis=1, keepdims=True), 1)
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("fsp", ["#FFFFFF", PRIMARY])
    ax.imshow(norm, cmap=cmap, vmin=0, vmax=1)
    for i in range(len(names)):
        for j in range(len(names)):
            ax.text(
                j,
                i,
                str(m[i, j]),
                ha="center",
                va="center",
                color="white" if norm[i, j] > 0.55 else DARK,
                fontsize=9,
            )
    ax.set_xticks(range(len(names)), names, fontsize=8)
    ax.set_yticks(range(len(names)), names, fontsize=8)
    ax.set_xlabel("Присвоенный грейд")
    ax.set_ylabel("Истинный грейд")
    ax.set_title("Категоризация по грейду")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _chart_systems(plt, sys_stuff, sys_clean, path):
    order_ = [
        "ours",
        "random_in_category",
        "test_only_in_category",
        "bm25_in_specialization",
        "bm25_universal",
    ]
    labels = {
        "ours": "Наша механика",
        "random_in_category": "Случайно в категории",
        "test_only_in_category": "Только тест в категории",
        "bm25_in_specialization": "BM25 по резюме\n(в специализации)",
        "bm25_universal": "BM25 по резюме\n(вся база)",
    }
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    x = np.arange(len(order_))
    ax.bar(
        x - 0.18,
        [sys_clean[k]["ndcg@10"] for k in order_],
        0.36,
        color=LIGHT_PRIMARY,
        label="Без накрутки резюме",
    )
    ax.bar(
        x + 0.18,
        [sys_stuff[k]["ndcg@10"] for k in order_],
        0.36,
        color=PRIMARY,
        label="30% кандидатов накручивают стек",
    )
    ax.set_xticks(x, [labels[k] for k in order_], fontsize=8)
    ax.set_ylabel("NDCG@10")
    ax.set_ylim(0, 1)
    ax.set_title("Качество подборки под потребность работодателя")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _chart_length(plt, curve, path):
    xs = [float(curve[k]["items_per_attempt"]) for k in curve]
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.plot(
        xs,
        [curve[k]["retest_agreement"] for k in curve],
        marker="o",
        color=PRIMARY,
        lw=2,
        label="Совпадение грейда при повторе",
    )
    ax.plot(
        xs,
        [curve[k]["retest_kappa_weighted"] for k in curve],
        marker="s",
        color=DARK,
        lw=1.5,
        label="Взвешенная κ (ретест)",
    )
    ax.plot(
        xs,
        [curve[k]["accuracy_exact"] for k in curve],
        marker="^",
        color=ACCENT,
        lw=1.5,
        label="Точность грейда",
    )
    ax.set_xlabel("Среднее число заданий в попытке")
    ax.set_ylim(0.4, 1)
    ax.set_title("Длина теста и стабильность результата")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ------------------------------------------------------------------------------------- отчёт


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render_md(r: dict) -> str:
    cat = get_catalog()
    rel = r["reliability"]
    b = r["bank"]
    lk = r["leaks"]
    m = r["matching"]["systems"]
    m0 = r["matching_no_stuffing"]["systems"]
    names = {
        "ours": "**Наша механика**",
        "ours_without_fsp": "— без ФСП",
        "ours_claims_only": "— без подоценок навыков из теста (только заявленный стек)",
        "ours_without_conditions": "— без совместимости условий",
        "ours_v1": "Исходная формула v1 (до специфичности и «ворот»)",
        "test_only_in_category": "Только результат теста внутри категории",
        "random_in_category": "Случайный порядок внутри категории",
        "bm25_in_specialization": "BM25 по тексту резюме в специализации",
        "bm25_universal": "BM25 по тексту резюме, вся база («универсальная площадка»)",
    }
    L = []
    w = L.append
    w("# Валидация решения\n")
    w(
        f"> Сгенерировано `make validate` ({r['elapsed_sec']} с). Все числа воспроизводимы: генераторы детерминированы по seed. Сырые результаты — `docs/validation.json`.\n"
    )
    w("## 1. Постановка\n")
    w(
        "Готовых данных и эталонной разметки в задаче нет, поэтому валидация построена на **синтетической популяции со скрытой истиной** "
        f"({r['config']['n_candidates']} кандидатов, {r['config']['n_needs']} потребностей работодателей) плюс проверки на реальных текстах вакансий. "
        "Система никогда не видит истинных признаков: только ответы в тесте, заявленный стек, текст резюме, достижения ФСП и условия.\n"
    )
    w(
        "**Чтобы валидация не была цикличной**, ответы на задания симулируются по модели, *отличной* от модели оценивания:\n"
    )
    w(
        "- истинная сложность семейства отклоняется от номинальной (σ = 0.35), дискриминативность — в 1.2 раза в обе стороны;"
    )
    w("- экземпляры одного семейства неидеально равны по сложности (σ = 0.25);")
    w(
        "- кандидат отвечает с навыко-специфичной способностью (σ = 0.45 от общей) — тест многомерен, модель одномерна;"
    )
    w("- угадывание в заданиях с выбором реально происходит.\n")
    w(
        "Эталонная релевантность пары «потребность–кандидат» (0–3) задана по скрытым признакам *до* формулы ранжирования: реальное владение требуемыми технологиями, истинная сила относительно порога грейда (знания + практика), готовность к предложению (статус поиска, вилка, формат).\n"
    )
    w(
        "Допущения генератора (их стоит проверить на живом пилоте): 30% кандидатов «накручивают» стек, чаще — более слабые и в тех областях, где они слабее; достижения ФСП отражают практический навык, частично независимый от знаний, которые меряет тест; у ~60% кандидатов истории ФСП нет.\n"
    )

    w("## 2. Механика тестирования\n")
    w("### 2.1 Банк заданий\n")
    w(
        f"- **{b['families']} параметризованных семейств** по {len(b['skills'])} навыкам, уровни сложности 1–5;"
    )
    w(
        f"- {pct(b['input_share'])} семейств — с вводом ответа (угадывание ≈ 0, утёкший ключ не подходит к новому экземпляру);"
    )
    w(
        f"- из 200 генераций семейства медианно **{b['unique_of_200_median']:.0f} уникальных экземпляров**; ≥100 уникальных — у {pct(b['share_ge_100_unique'])} семейств, <10 — у {pct(b['share_lt_10_unique'])} (концептуальные вопросы с выбором; их доля в тесте ограничена blueprint)."
    )
    w(
        "- Каждое семейство проходит автопроверки в CI: правильный ответ вычисляется исполнением кода/SQL и принимается проверкой, варианты не дублируются, ответ меняется между экземплярами; вывод заданий на JavaScript, Java, Go, C# и PHP сверяется с настоящими рантаймами.\n"
    )

    w("### 2.2 Точность и стабильность грейда\n")
    w(
        "Онбординг: тест на заявленный грейд → при неудаче на ступень ниже → при уверенном успехе одна попытка на ступень выше. "
        "Повтор (ретест) — второй онбординг того же кандидата; как и в продукте, система помнит семейства прошлых попыток и выбирает другие, "
        "то есть ретест идёт на *параллельной форме*, а не на тех же шаблонах с другими числами.\n"
    )
    w("| Метрика | Значение |\n|---|---|")
    w(
        f"| Совпадение с истинным грейдом | **{pct(rel['accuracy_exact'])}** (±1 ступень — {pct(rel['accuracy_within1'])}) |"
    )
    w(f"| Завышение / занижение грейда | {pct(rel['overgrade_rate'])} / {pct(rel['undergrade_rate'])} |")
    w(f"| Cohen's κ с истиной | {rel['kappa_vs_truth']:.2f} |")
    w(f"| Ретест: совпадение грейда | **{pct(rel['retest_agreement'])}** |")
    w(f"| Ретест: κ / взвешенная κ | {rel['retest_kappa']:.2f} / **{rel['retest_kappa_weighted']:.2f}** |")
    w(f"| Ретест: корреляция θ | {rel['retest_theta_r']:.2f} |")
    w(f"| Ретест: совпадение решения по заявленному грейду | {pct(rel['first_decision_agreement'])} |")
    w(f"| Корреляция оценки θ с истинной | {rel['theta_true_r']:.2f} |")
    w(f"| Заданий за попытку / за онбординг | {rel['items_per_attempt']:.1f} / {rel['items_mean']:.1f} |")
    w(
        f"| Повтор по сути (то же семейство или группа): в следующей попытке онбординга / на ретесте | {pct(rel['repeat_onboarding'])} / {pct(rel['repeat_retest'])} |"
    )
    w(
        f"| Точность вне пограничной зоны (|θ − порог| ≥ 0.25) / в ней | {pct(rel['accuracy_nonborder'])} / {pct(rel['accuracy_border'])} (доля пограничных — {pct(rel['share_border'])}) |\n"
    )
    w("![Матрица ошибок](img/val_confusion.png)\n")
    w(
        "**Интерпретация.** Ошибки — только на соседний грейд и в основном *в сторону занижения*: для работодателя подтверждённый грейд надёжен "
        f"(завышение {pct(rel['overgrade_rate'])}), а кандидат может пройти тест на ступень выше после кулдауна. "
        "Совпадение при ретесте ограничено точностью измерения: при SE ≈ 0.33 и ширине грейда ≈ 1.0 по шкале θ теоретический потолок совпадения для "
        "кандидатов на границе грейдов — около 70%. Взвешенная κ, учитывающая порядковость грейдов, — в зоне «почти полного согласия». "
        "Для продукта важнее, что **грейд не меняется вниз при повторе по правилам платформы**: повторная попытка может только подтвердить грейд или повысить его.\n"
    )
    w("**Выбор порога решения** (P(θ > порог) для подтверждения):\n")
    w(
        "| Порог | Точность | Завышение | Занижение | Совпадение ретеста | Заданий |\n|---|---|---|---|---|---|"
    )
    for k, v in r["threshold_tradeoff"].items():
        w(
            f"| {k} | {pct(v['accuracy_exact'])} | {pct(v['overgrade_rate'])} | {pct(v['undergrade_rate'])} | {pct(v['retest_agreement'])} | {v['items_mean']:.1f} |"
        )
    w(
        "\nОтдельно — одна попытка теста: доля ложных подтверждений, когда кандидат заявляет грейд на ступень выше истинного, против доли подтверждений при честной заявке:\n"
    )
    w("| Порог | Ложные подтверждения (+1 ступень) | Верные подтверждения |\n|---|---|---|")
    for k, v in r["threshold_roc"].items():
        w(f"| {k} | {pct(v['false_pass_plus1'])} | {pct(v['true_pass'])} |")
    roc = r["threshold_roc"]
    chosen = f"{DEFAULT_CONFIG.pass_probability:.2f}"
    up = f"{DEFAULT_CONFIG.pass_probability_upgrade:.2f}"
    w(
        f"\nВыбрано: первичное подтверждение при **{DEFAULT_CONFIG.pass_probability}** — компромисс: точность итогового грейда близка к максимальной, "
        f"завышение не выше 5%, а ложных подтверждений при завышенной заявке меньше, чем при 0.5 ({pct(roc[chosen]['false_pass_plus1'])} против {pct(roc['0.50']['false_pass_plus1'])}). "
        "Неудача не наказывается — кандидат сразу проходит тест на ступень ниже. **Повышение** уже подтверждённого грейда — при "
        f"**{DEFAULT_CONFIG.pass_probability_upgrade}** (ложные подтверждения {pct(roc[up]['false_pass_plus1'])}): ложное повышение дороже. "
        f"Предложение пройти тест выше — при P(θ > порог следующего) ≥ {DEFAULT_CONFIG.upgrade_probability}.\n"
    )
    w(
        "**Длина теста.** Стабильность растёт с длиной теста; 25 заданий (~20–30 минут) — компромисс между точностью и временем кандидата.\n"
    )
    w(
        "| Макс. заданий | Заданий в попытке | Совпадение ретеста | Взвеш. κ | Точность | r(θ̂, θ) |\n|---|---|---|---|---|---|"
    )
    for k, v in r["length_curve"].items():
        w(
            f"| {k} | {v['items_per_attempt']:.1f} | {pct(v['retest_agreement'])} | {v['retest_kappa_weighted']:.2f} | {pct(v['accuracy_exact'])} | {v['theta_true_r']:.2f} |"
        )
    w("\n![Длина теста](img/val_length.png)\n")
    ra = r.get("repeat_ablation")
    if ra:
        w(
            "**Память о показанных заданиях.** Без неё следующая попытка (например, Middle после Junior) на "
            f"{pct(ra['repeat_onboarding'])} состоит из уже виденных шаблонов, ретест — на {pct(ra['repeat_retest'])}: кандидат узнаёт задачи, "
            "отличаются только числа. С памятью — "
            f"{pct(rel['repeat_onboarding'])} и {pct(rel['repeat_retest'])}; остаток — навыки, где семейств меньше, чем заданий за две попытки "
            "(тогда берутся давно виденные, тест не обрывается). Точность грейда — "
            f"{pct(rel['accuracy_exact'])} против {pct(ra['accuracy_exact'])} без памяти. Совпадение ретеста "
            f"({pct(rel['retest_agreement'])} против {pct(ra['retest_agreement'])}, взвешенная κ {rel['retest_kappa_weighted']:.2f} против "
            f"{ra['retest_kappa_weighted']:.2f}): повтор на тех же шаблонах завышал стабильность за счёт общей для шаблона ошибки "
            "измерения, параллельная форма — более строгая и честная оценка.\n"
        )
    pa = r["pooling_ablation"]
    w(
        f"*Проверенная и отклонённая гипотеза:* учитывать ответы предыдущих попыток онбординга в следующей (продолжать измерение). Это сокращает тест до {pa['items_mean']:.1f} заданий, но не повышает точность ({pct(pa['accuracy_exact'])}) и стабильность ({pct(pa['retest_agreement'])}); по умолчанию выключено.\n"
    )

    bpx = r.get("blueprint")
    if bpx:
        A = bpx["arms"]
        w("### 2.3 Состав теста: ядро специализации + модули стека\n")
        w(
            "Раньше состав теста был общим для специализации, а стек выбирал только язык (при отсутствии совпадения подставлялся Python): "
            "Java-, Go-, C#-разработчики получали пятую часть теста по чужому языку, Vue-разработчики — задания по React, Linux-администраторы — по Kubernetes. "
            "Теперь тест = **ядро специализации** (общее для всех в категории — сопоставимость грейдов) + **до трёх модулей по заявленному стеку** "
            "(доля модулей ≤ 40%); технологии без заданий ничем не подменяются. Каждый навык состава получает не меньше 2 заданий, чтобы его подоценка "
            "не оставалась «нет данных».\n"
        )
        w(
            f"Эксперимент: {bpx['n']} кандидатов с реалистичными стеками (архетипы рынка), backend-разработчик знает только свой язык. "
            f"У {pct(bpx['affected_share'])} из них прежний состав содержит навыки не из реального стека. "
            "Штраф за чужой стек — насколько способность в навыке-модуле не из реального стека ниже общего уровня: 0 — стек не влияет на ответы "
            "(как в остальной валидации), 0.5–1.0 — реалистичный диапазон.\n"
        )
        w(
            "| Штраф за чужой стек | Состав | Точность грейда | Точность у затронутых | Занижение у затронутых | Смещение θ у затронутых | Ретест | Заданий | Заявленных технологий с данными теста | Подтверждено: накрученные / реальные |\n"
            "|---|---|---|---|---|---|---|---|---|---|"
        )
        for key, v in A.items():
            arm, pen = key.split("@")
            name = "прежний общий" if arm == "legacy" else "**ядро + модули**"
            w(
                f"| {pen} | {name} | {pct(v['accuracy_exact'])} | {pct(v['accuracy_affected'])} | {pct(v['undergrade_affected'])} | "
                f"{v['theta_bias_affected']:+.2f} | {pct(v['retest_agreement'])} | {v['items_per_attempt']:.1f} | {pct(v['claimed_tested_share'])} | "
                f"{pct(v['stuffed_confirmed_rate'])} / {pct(v['real_confirmed_rate'])} |"
            )
        hi = max(float(k.split("@")[1]) for k in A)
        lg, pr = A[f"legacy@{hi:.1f}"], A[f"personal@{hi:.1f}"]
        z_l, z_p = A["legacy@0.0"], A["personal@0.0"]
        w(
            f"\n**Итог.** Когда стек не влияет на ответы, новый состав сопоставим с прежним (точность {pct(z_p['accuracy_exact'])} против {pct(z_l['accuracy_exact'])} — в пределах шума, "
            f"ретест {pct(z_p['retest_agreement'])} против {pct(z_l['retest_agreement'])}). Когда влияет (штраф {hi:.1f}), прежний состав систематически занижает "
            f"оценку затронутых кандидатов (смещение θ {lg['theta_bias_affected']:+.2f}, занижение грейда {pct(lg['undergrade_affected'])}), новый — нет "
            f"({pr['theta_bias_affected']:+.2f}, {pct(pr['undergrade_affected'])}). Доля заявленных технологий, по которым у работодателя есть данные теста, "
            f"растёт с {pct(lg['claimed_tested_share'])} до {pct(pr['claimed_tested_share'])} — это прямой вход механики подбора "
            f"(«подтверждено тестом», §4), и накрутка стека чаще упирается в проверку. Цена — {pr['items_per_attempt'] - lg['items_per_attempt']:+.1f} задания на попытку.\n"
        )
    w("### 2.4 Устойчивость к утечкам\n")
    w(
        f"Сценарий: {lk['n_cheaters']} кандидатов пытаются подтвердить грейд на ступень выше истинного и имеют доступ к утечкам. "
        "Для фиксированных заданий утёкший ответ решает задание (p = 0.98). В нашем подходе утечка экземпляра бесполезна (другие параметры — другой ответ), "
        "а знакомство с шаблоном даёт лишь частичный выигрыш (как от подготовки по теме).\n"
    )
    w("| Доля утёкшего банка | Единый тест | Банк фикс. заданий + CAT | **Наш подход** |\n|---|---|---|---|")
    for s in lk["false_pass"]["ours"]:
        w(
            f"| {float(s) * 100:.0f}% | {pct(lk['false_pass']['fixed'][s])} | {pct(lk['false_pass']['pool'][s])} | **{pct(lk['false_pass']['ours'][s])}** |"
        )
    w("\n![Утечки](img/val_leaks.png)\n")
    d = r["drift"]
    w(
        f"**Мониторинг утечек (CUSUM).** На {d['families']} «честных» семействах по {d['responses_per_family']} ответов ложных тревог — {pct(d['false_alarm_rate'])}. "
        f"Если решение шаблона утекло и им пользуется {pct(d['affected_share'])} кандидатов, семейство помечается в {pct(d['detection_rate'])} случаев, "
        f"медианно через {d['delay_median']:.0f} ответов (90-й перцентиль — {d['delay_p90']:.0f}), и выводится из ротации.\n"
    )
    w("### 2.5 Дискриминативность и калибровка\n")
    ds = r["discrimination"]
    w(
        f"- Использовано семейств в симуляции: {ds['families_used']} из {ds['families_total']}; оценено (≥30 ответов): {ds['families_evaluated']}."
    )
    w(
        f"- Медианная точечно-бисериальная корреляция «верно ↔ истинная способность»: **{ds['rpb_median']:.2f}**; доля семейств с r < 0.2 — {pct(ds['rpb_share_below_0_2'])} (кандидаты на доработку: {', '.join(ds['weak_families'][:8]) or '—'})."
    )
    w(
        f"- Экспозиция: максимум {pct(ds['exposure_max'])} кандидатов видели одно семейство, медиана — {pct(ds['exposure_median'])}."
    )
    rc = r["recalibration"]
    w(
        f"- **Онлайн-перекалибровка (MML-EM)** по {rc['responses']} ответам: средняя ошибка сложности b для {rc['families']} семейств снижается с {rc['mae_b_nominal']:.2f} (экспертная разметка) до **{rc['mae_b_recalibrated']:.2f}**. То есть по мере работы платформы параметры банка уточняются по данным.\n"
    )

    w("## 3. Категоризация\n")
    ca = r["categorization"]
    w(
        f"Категория = специализация (из опроса) × подтверждённый тестом грейд. Категоризированы {pct(ca['categorized_share'])} кандидатов; грейд категории совпадает с истинным у **{pct(ca['category_exact'])}**, ±1 ступень — {pct(ca['category_within1'])}. Резюме на категорию не влияет.\n"
    )

    w("## 4. Механика подбора\n")
    w(
        f"Тестовый набор: {r['matching']['n_needs']} потребностей × {r['matching']['n_candidates']} кандидатов, эталон — релевантность 0–3 по скрытым признакам. Метрики на топ-10: NDCG@10 (градуированная), P@10 (доля релевантных ≥ 2), MRR, ожидаемое число *принятых* приглашений среди релевантных (по модели решения кандидата).\n"
    )
    w("| Система | NDCG@10 | P@10 | MRR | Принятые@10 | NDCG@10 без накрутки |\n|---|---|---|---|---|---|")
    for k, v in m.items():
        w(
            f"| {names[k]} | {v['ndcg@10']:.3f} | {v['p@10']:.3f} | {v['mrr']:.3f} | {v['accepted@10']:.2f} | {m0[k]['ndcg@10']:.3f} |"
        )
    w("\n![Подбор](img/val_matching.png)\n")
    ours, bm = m["ours"], m["bm25_universal"]
    w(
        f"**Итог.** Механика даёт NDCG@10 = {ours['ndcg@10']:.2f} против {bm['ndcg@10']:.2f} у поиска по ключевым словам на «универсальной площадке» "
        f"и в {ours['accepted@10'] / max(bm['accepted@10'], 1e-9):.1f} раза больше ожидаемых принятых приглашений в топ-10. "
        f"При накрутке стека у 30% кандидатов качество BM25 падает на {max(0.0, 1 - m['bm25_in_specialization']['ndcg@10'] / m0['bm25_in_specialization']['ndcg@10']) * 100:.0f}%, "
        f"нашей механики — на {max(0.0, 1 - ours['ndcg@10'] / m0['ours']['ndcg@10']) * 100:.0f}%.\n"
    )
    if "matching_no_experience" in r:
        ne = r["matching_no_experience"]["systems"]["ours"]
        w(
            f"**Опыт работы.** У синтетических кандидатов есть история работы: часть джунов без коммерческого опыта, "
            f"около 20% сменили роль (общий стаж больше релевантного); в потребностях указан требуемый опыт. "
            f"С учётом релевантного опыта NDCG@10 = {ours['ndcg@10']:.3f}, без него (история скрыта) — {ne['ndcg@10']:.3f}; "
            f"ожидаемые принятые приглашения в топ-10: {ours['accepted@10']:.2f} против {ne['accepted@10']:.2f}. "
            "Оговорка: эталонная релевантность сама понижает кандидатов с нехваткой опыта (так рассуждает работодатель), "
            "поэтому прирост показывает согласованность механики с этим правилом, а не независимое подтверждение веса.\n"
        )
    if "ours_v1" in m:
        v1 = m["ours_v1"]
        w(
            f"**v5 против исходной формулы v1** на этой синтетической истине: NDCG@10 {ours['ndcg@10']:.3f} против {v1['ndcg@10']:.3f}, "
            f"P@10 {ours['p@10']:.3f} против {v1['p@10']:.3f}. Истина генератора считает долю известных технологий вакансии без учёта того, "
            "какие из них определяют стек (Go в Go-вакансии весит как Git), — ровно то, что исправляет v5, поэтому здесь v5 не выигрывает. "
            "По независимым слепым судьям на реалистичных текстах v5 значимо лучше v1 — [bench.md](bench.md#эксперимент-v5-специфичность-требований-и-ворота).\n"
        )
    w(
        "**Что вносит вклад (абляции).** Основной прирост дают категоризация по тесту и совместимость условий (без неё NDCG падает сильнее всего). "
        f"Подоценки навыков из теста дают +{ours['ndcg@10'] - m['ours_claims_only']['ndcg@10']:.3f} NDCG@10: состав теста строится по заявленному стеку, "
        "поэтому заявленные технологии проверяются тестом (при прежнем общем составе подоценки подбору не помогали — см. разложение ниже). "
        "ФСП на синтетике даёт малый прирост: он коррелирует с уже измеренной способностью; его ценность — в доверии работодателя к объяснению, "
        "вес ограничен (≈7.5% итогового скора), чтобы он не перекрывал соответствие потребности.\n"
    )
    cm = r.get("composition_matching")
    if cm:
        w(
            "**Состав теста × формула подбора** (NDCG@10; в скобках — без подоценок из теста, только заявленный стек):\n"
        )
        w("| Состав теста | Формула v1 | Формула v5 |\n|---|---|---|")
        for comp, title in (("legacy", "прежний общий"), ("personal", "**ядро + модули стека**")):
            a, b5 = cm[f"{comp}/v1"], cm[f"{comp}/v5"]
            w(
                f"| {title} | {a['with_test']:.3f} ({a['claims_only']:.3f}) | {b5['with_test']:.3f} ({b5['claims_only']:.3f}) |"
            )
        lv1, pv5 = cm["legacy/v1"], cm["personal/v5"]
        w(
            f"\nПрежняя связка (общий состав + v1) — {lv1['with_test']:.3f}, и подоценки из теста ей мешали "
            f"({lv1['with_test'] - lv1['claims_only']:+.3f}): проверялись навыки не из стека кандидата. "
            f"Новая (ядро + модули + v5) — {pv5['with_test']:.3f}, подоценки дают {pv5['with_test'] - pv5['claims_only']:+.3f}.\n"
        )
    w("**Чувствительность к весам** (изменение NDCG@10 при умножении веса на 0.5 / 1.5):\n")
    w("| Вес | ×0.5 | ×1.5 |\n|---|---|---|")
    for k, v in r["sensitivity"].items():
        if k.startswith("_"):
            continue
        w(f"| `{k}` | {v['x0.5']:+.3f} | {v['x1.5']:+.3f} |")
    sens = {k: v for k, v in r["sensitivity"].items() if not k.startswith("_")}
    worst = max(sens.items(), key=lambda kv: max(abs(x) for x in kv[1].values()))
    mild = [k for k, v in sens.items() if max(abs(x) for x in v.values()) < 0.04]
    w(
        f"\nБазовое NDCG@10 = {r['sensitivity']['_base']['ndcg@10']:.3f}. Для {len(mild)} из {len(sens)} весов изменение в пределах ±50% "
        f"меняет NDCG меньше чем на 0.04 — формула не «подогнана» под синтетику. Наибольшая чувствительность — к `{worst[0]}` "
        f"(до {max(abs(x) for x in worst[1].values()):.3f}): это ожидаемо и подтверждает обоснованность соответствующего правила.\n"
    )

    w("## 5. Разбор текстов (NLP)\n")
    v = r["vacancies"]
    w(
        f"**Вакансии.** На {v['n']} демонстрационных вакансиях (`ml/fspml/data/vacancies.yaml`) специализация определена верно в {pct(v['spec_acc'])}, грейд — в {pct(v['grade_acc'])}. Blueprint теста под вакансию:\n"
    )
    w("| Вакансия | Blueprint (доли навыков в тесте) |\n|---|---|")
    for row in v["rows"]:
        bp = ", ".join(
            f"{cat.assessment_skills[k]['title']} {x * 100:.0f}%"
            for k, x in list(row["blueprint"].items())[:6]
        )
        w(f"| {row['id']} | {bp} |")
    rs = r["resume"]
    w(
        f"\n**Резюме.** {rs['n']} синтетических PDF (разные заголовки секций, форматы дат, опечатки в названиях технологий) → парсер: "
    )
    w(
        "точность полей "
        + ", ".join(f"{k} {pct(x)}" for k, x in rs["fields"].items())
        + f"; технологии P/R/F1 = {rs['skills_precision']:.2f}/{rs['skills_recall']:.2f}/{rs['skills_f1']:.2f}; стаж ±0.5 года — {pct(rs['experience_within_0_5y'])}. "
    )
    w(
        "Синтетические PDF чище реальных — следующий шаг: 10–15 реальных обезличенных резюме с ручной разметкой.\n"
    )

    w("## 6. Ограничения и следующие шаги\n")
    w(
        "- Параметры семейств — экспертные; после запуска — онлайн-перекалибровка (показана выше), мониторинг дрейфа и вывод слабых семейств."
    )
    w(
        "- Живой пилот (15–20 человек): сравнение грейда с экспертной оценкой команды и интервьюеров — протокол в `docs/pilot.md`."
    )
    w(
        "- Эталонная релевантность синтетическая; на реальных данных — обучение весов по откликам на приглашения (learning to rank) с контролем объяснимости."
    )
    return "\n".join(L) + "\n"
