"""Витрина: одна вакансия — два порядка выдачи (v5 и v7), где достижения ФСП перевешивают тест.

python -m fspml.validation.showcase [--out docs]

Популяция и потребности — те же, что в синтетической валидации (`make validate`). Среди вакансий
Junior/Middle выбирается та, где в топ-10 v7 участник ФСП обходит кандидата с более высоким
результатом теста, а в v5 стоял ниже него. Для пары выводится разложение скора: вклад силы профиля,
множитель опыта и причины в выдаче — то, что видит работодатель.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..catalog import get_catalog
from ..matching.scoring import WEIGHTS_V7, Scored, fsp_strength, rank, required_years
from ..nlp.embed import HashingEmbedder
from . import assessment as va
from . import matching as vm
from .population import TODAY, make_candidates, make_needs

K = 10


def _years(f) -> str:
    if f.relevant_years is None and f.experience_years is None:
        return "не указан"
    return f"{f.relevant_years or 0:.1f} г"


def _fsp_text(f, catalog) -> str:
    if f.fsp is None:
        return "ID не привязан"
    if not f.fsp:
        return "достижений нет"
    best = max(
        f.fsp, key=lambda a: catalog.fsp_weight("levels", a.level) * catalog.fsp_weight("results", a.result)
    )
    res = next(x["title"] for x in catalog.fsp["results"] if x["id"] == best.result).lower()
    lvl = next(x["title"] for x in catalog.fsp["levels"] if x["id"] == best.level).lower()
    return f"{res}, {lvl}, {best.event_date.year}" + (f" (+{len(f.fsp) - 1})" if len(f.fsp) > 1 else "")


def find_case(feats, needs, emb):
    """Лучшая пара (участник ФСП, кандидат с более высоким тестом): сначала — участник ФСП с нехваткой
    стажа (ради кого v7 и сделана), затем — наибольший подъём в выдаче."""
    by_id = {f.id: f for f in feats}
    best = None
    for tn in needs:
        if tn.grade not in ("junior", "middle"):
            continue
        need = vm.to_need(tn, emb)
        v5 = rank(feats, need, TODAY, version=5)
        v7 = rank(feats, need, TODAY, version=7)
        p5 = {s.candidate_id: i for i, s in enumerate(v5)}
        req, _ = required_years(need)
        top7 = [s.candidate_id for s in v7[:K]]
        for i, x in enumerate(top7):
            fx = by_id[x]
            if not fx.fsp or fx.theta is None:
                continue
            for y in top7[i + 1 :]:
                fy = by_id[y]
                if fy.theta is None or fy.theta <= fx.theta or p5[y] > p5[x]:
                    continue
                gain = p5[x] - i
                short = (fx.relevant_years or 0.0) < req
                key = (short, tn.grade == "junior", gain, -abs(fy.theta - fx.theta))
                if best is None or key > best[0]:
                    best = (key, tn, need, v5, v7, x, y)
    return best


def render(feats, case) -> str:
    catalog = get_catalog()
    by_id = {f.id: f for f in feats}
    _, tn, need, v5, v7, x, y = case
    s5 = {s.candidate_id: s for s in v5}
    s7 = {s.candidate_id: s for s in v7}
    p5 = {s.candidate_id: i + 1 for i, s in enumerate(v5)}
    p7 = {s.candidate_id: i + 1 for i, s in enumerate(v7)}
    fx, fy = by_id[x], by_id[y]
    grade = catalog.grade(need.grade).name
    L: list[str] = []
    w = L.append
    w("# Витрина: один кандидат — два порядка выдачи\n")
    w(
        "> Сгенерировано `python -m fspml.validation.showcase`. Популяция и потребности — синтетическая валидация "
        "([validation.md](validation.md)); формулы — [matching.md](matching.md).\n"
    )
    skills = ", ".join(f"{t} ({imp:.2f})" for t, imp in sorted(need.skills.items(), key=lambda kv: -kv[1]))
    w(f"**Вакансия:** {catalog.specializations[need.specialization].name} · {grade}")
    req, explicit = required_years(need)
    w(
        f"требуемые технологии (важность): {skills}; опыт — от {req:g} г ({'указан в вакансии' if explicit else 'типичный для грейда'}).\n"
    )
    w(
        f"**Главное.** Кандидат `{x}` — участник ФСП ({_fsp_text(fx, catalog)}), релевантный опыт {_years(fx)}. "
        f"У кандидата `{y}` тест выше (θ {fy.theta:+.2f} против {fx.theta:+.2f}), "
        f"опыт {_years(fy)}, ФСП: {_fsp_text(fy, catalog)}. "
        f"В v5 `{x}` на {p5[x]}-м месте, `{y}` — на {p5[y]}-м; в v7 `{x}` поднимается на {p7[x]}-е, `{y}` — {p7[y]}-е.\n"
    )
    w("## Почему: разложение скора\n")
    w("| | v5: `" + x + "` | v5: `" + y + "` | v7: `" + x + "` | v7: `" + y + "` |")
    w("|---|---|---|---|---|")
    rows = [
        ("Место в выдаче", lambda s, c: str(p5[c] if s is s5 else p7[c])),
        ("Итоговый скор", lambda s, c: f"{s[c].score:.3f}"),
        ("Вклад силы профиля", lambda s, c: f"{s[c].components['profile']:.3f}"),
        ("— тест (0..1)", lambda s, c: f"{s[c].details['test']:.2f}"),
        ("— ФСП (0..1)", lambda s, c: f"{s[c].details['fsp']:.2f}"),
        ("Вклад соответствия навыкам", lambda s, c: f"{s[c].components['need_fit']:.3f}"),
        ("Множитель опыта", lambda s, c: f"×{s[c].details.get('gate_experience', 1.0):.2f}"),
    ]
    for title, fn in rows:
        w(f"| {title} | {fn(s5, x)} | {fn(s5, y)} | {fn(s7, x)} | {fn(s7, y)} |")
    w("")
    w(
        f"Доля ФСП в итоговом скоре: v5 — 0.30 × 0.25 = 7.5%, v7 — {WEIGHTS_V7.profile:.2f} × {WEIGHTS_V7.ps_fsp:.2f} = "
        f"{WEIGHTS_V7.profile * WEIGHTS_V7.ps_fsp:.0%}. Сила ФСП `{x}`: {fsp_strength(fx.fsp, fx.specialization, TODAY):.2f}.\n"
    )
    w(f"## Что видит работодатель в карточке `{x}` (v7)\n")
    for r in s7[x].reasons:
        mark = {"positive": "✅", "neutral": "⚪", "negative": "⚠️"}[r.kind]
        w(f"- {mark} {r.text}")
    w("")
    w("## Топ-10: v5 и v7\n")
    w("| # | v5 | θ | ФСП | опыт | v7 | θ | ФСП | опыт |")
    w("|---|---|---|---|---|---|---|---|---|")

    def cell(s: Scored) -> str:
        f = by_id[s.candidate_id]
        name = f"**{s.candidate_id}**" if s.candidate_id in (x, y) else s.candidate_id
        th = f"{f.theta:+.2f}" if f.theta is not None else "—"
        return f"{name} | {th} | {_fsp_text(f, catalog)} | {_years(f)}"

    for i in range(K):
        w(f"| {i + 1} | {cell(v5[i])} | {cell(v7[i])} |")
    w("")
    w(
        "Где категория выше теста: внутри одной категории порядок по-прежнему начинается с теста (вес теста в силе профиля "
        f"{WEIGHTS_V7.ps_test:.2f} ≥ веса ФСП {WEIGHTS_V7.ps_fsp:.2f}), а достижения ФСП решают, когда тесты близки и у "
        "участника соревнований нет коммерческого стажа. «Ворота» основного стека ФСП не обходит.\n"
    )
    return "\n".join(L)


def run(out_dir: Path) -> Path:
    cands = make_candidates(1000, stuffing_rate=0.3, history=True)
    truth = va.make_true_bank()
    needs = make_needs(30, history=True)
    obs = vm.observe(cands, truth)
    case = find_case(obs.features, needs, HashingEmbedder())
    if case is None:
        raise SystemExit("Подходящий пример не найден")
    path = out_dir / "fsp-showcase.md"
    path.write_text(render(obs.features, case), encoding="utf-8")
    return path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default="docs", type=Path)
    print(run(p.parse_args().out))


if __name__ == "__main__":
    main()
