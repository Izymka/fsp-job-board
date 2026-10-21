"""bench3: живые тексты вакансий × обезличенные профили — как меняется выдача от v5 к v7.

python -m fspml.bench.live [--out docs]

Вакансии — 10 реальных открытых объявлений Junior/Middle с Хабр Карьеры (`ml/bench3/vacancies.json`,
без названий компаний). Разбор вакансии — наш NLP (`parse_need`); специализация и грейд берутся из
разметки площадки (так работодатель исправляет разбор вручную), расхождения разбора выводятся в отчёт.
Кандидаты — 20 обезличенных собирательных профилей (`ml/bench3/candidates.yaml`), не реальные люди.

Это иллюстрация на малой выборке, а не статистика: метрика качества выдачи здесь не считается, отчёт
показывает порядок выдачи v5 и v7 и где оказываются участники ФСП без коммерческого опыта.

Отдельно — точность грейда по тексту вакансии на 50 вакансиях (эти 10 + 40 из `ml/bench3/grade_vacancies.json`,
квоты по грейдам и специализациям). Поле `split` (dev/test) задаётся хешем id: правила разбора настраивались
только на dev, test — контроль. Вилка берётся из полей площадки, как из формы работодателя.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import yaml

from ..catalog import get_catalog
from ..matching.scoring import CandidateFeatures, FspAchievement, Need, rank
from ..nlp.vacancy import ParsedNeed, estimate_grade, parse_need

ROOT = Path(__file__).resolve().parents[2] / "bench3"
TODAY = date(2026, 10, 21)


def load_candidates(path: Path = ROOT / "candidates.yaml") -> list[CandidateFeatures]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))["candidates"]
    out = []
    for r in rows:
        years = r.get("years")
        fsp = r.get("fsp")
        out.append(
            CandidateFeatures(
                id=r["id"],
                specialization=r["spec"],
                grade=r["grade"],
                theta=r["theta"],
                theta_se=0.35,
                skill_status=dict(r.get("skills", {})),
                claimed=set(r["stack"]),
                fsp=None
                if fsp is None
                else [FspAchievement(d, lvl, res, date.fromisoformat(str(dt))) for d, lvl, res, dt in fsp],
                salary_from=r["salary"][0],
                salary_to=r["salary"][1],
                work_formats=set(r["formats"]),
                search_status="active",
                last_active=TODAY,
                tested_at=TODAY,
                relevant_years=years[0] if years else None,
                it_years=years[1] if years else None,
                experience_years=years[1] if years else None,
            )
        )
    return out


def load_vacancies(*names: str) -> list[dict]:
    return [v for n in names for v in json.loads((ROOT / n).read_text(encoding="utf-8"))]


def grade_bench() -> list[tuple[dict, ParsedNeed]]:
    return [
        (v, parse_need(v["text"], v["title"], v.get("salary_from"), v.get("salary_to")))
        for v in load_vacancies("vacancies.json", "grade_vacancies.json")
    ]


def grade_section(rows: list[tuple[dict, ParsedNeed]]) -> list[str]:
    cat = get_catalog()
    L = ["## Грейд по тексту вакансии: dev и test\n"]
    w = L.append
    w(
        f"{len(rows)} реальных вакансий Хабр Карьеры; эталон — квалификация, которую работодатель указал на площадке. "
        "Грейд — взвешенное голосование сигналов: заголовок (решает сам), требуемый стаж, уровень в тексте "
        "без упоминаний коллег, лексика уровня, вилка относительно медиан специализации (`grade_salary` в каталоге). "
        "Уверенность: high — заголовок или согласие ≥2 сигналов, medium — один сигнал, low — конфликт или сигналов нет "
        "(тогда грейд не предлагается и работодатель выбирает его вручную). Правила настраивались только на dev.\n"
    )
    w("| Часть | Вакансий | Грейд верен | Верен при high | Доля low | Без грейда в заголовке: верно |")
    w("|---|---|---|---|---|---|")
    for split in ("dev", "test"):
        part = [(v, p) for v, p in rows if v["split"] == split]
        ok = sum(p.grade == v["grade"] for v, p in part)
        high = [(v, p) for v, p in part if p.grade_confidence == "high"]
        ok_high = sum(p.grade == v["grade"] for v, p in high)
        low = sum(p.grade_confidence == "low" for _, p in part)
        untitled = [
            (v, p)
            for v, p in part
            if not any(s.kind == "title" for s in estimate_grade(v["title"], "").signals)
        ]
        ok_untitled = sum(p.grade == v["grade"] for v, p in untitled)
        w(
            f"| {split} | {len(part)} | {ok} из {len(part)} ({ok / len(part):.0%}) | {ok_high} из {len(high)} "
            f"| {low / len(part):.0%} | {ok_untitled} из {len(untitled)} |"
        )
    for split in ("dev", "test"):
        w(f"\nОшибки {split}:\n")
        for v, p in rows:
            if v["split"] == split and p.grade != v["grade"]:
                got = cat.grade(p.grade).name if p.grade else "не определён"
                w(
                    f"- «{v['title']}» ({v['id']}): разбор — {got} [{p.grade_confidence}], на площадке — "
                    f"{cat.grade(v['grade']).name}; сигналы: {p.grade_reason}"
                )
    w("")
    return L


def load_needs(path: Path = ROOT / "vacancies.json") -> list[tuple[dict, Need, dict]]:
    out = []
    for v in json.loads(path.read_text(encoding="utf-8")):
        p = parse_need(v["text"], v["title"], v.get("salary_from"), v.get("salary_to"))
        need = Need(
            specialization=v["specialization"],
            grade=v["grade"],
            skills=dict(p.skills),
            salary_from=v.get("salary_from") or p.salary_from,
            salary_to=v.get("salary_to") or p.salary_to,
            work_format=p.work_format,
            min_years=p.min_years,
            text=v["text"],
        )
        parsed = {"specialization": p.specialization, "grade": p.grade}
        out.append((v, need, parsed))
    return out


def _young_fsp(c: CandidateFeatures) -> bool:
    return bool(c.fsp) and (c.relevant_years or 0.0) < 1.0


def report() -> str:
    cat = get_catalog()
    cands = load_candidates()
    by_id = {c.id: c for c in cands}
    needs = load_needs()
    L: list[str] = []
    w = L.append
    w("# bench3: живые вакансии, v5 против v7\n")
    w(
        "> Сгенерировано `python -m fspml.bench.live`. 10 реальных открытых вакансий Junior/Middle с Хабр Карьеры "
        "(тексты — `ml/bench3/vacancies.json`, без названий компаний) × 20 обезличенных собирательных профилей "
        "(`ml/bench3/candidates.yaml`: стек, стаж и достижения — типовые для открытых резюме и итоговых таблиц ФСП; "
        "реальных людей нет). Иллюстрация на малой выборке, не статистика.\n"
    )
    ok_spec = sum(parsed["specialization"] == v["specialization"] for v, _, parsed in needs)
    w(
        f"**Разбор живых текстов нашим NLP.** Специализация верна в {ok_spec} из {len(needs)} "
        "(эталон — специализация на площадке); точность грейда — в разделе ниже, на 50 вакансиях. Ошибки специализации:\n"
    )
    for v, _, parsed in needs:
        if parsed["specialization"] != v["specialization"]:
            w(
                f"- «{v['title']}»: разбор — {parsed['specialization'] or '—'}, на площадке — {v['specialization']}"
            )
    w(
        "\nВ продукте разбор показывается работодателю с объяснением и исправляется вручную; в выдаче ниже "
        "специализация и грейд — с площадки.\n"
    )
    L.extend(grade_section(grade_bench()))
    w("## Выдача по вакансиям\n")
    w("Жирным — участники ФСП с релевантным стажем меньше года. ↑/↓ — сдвиг позиции в v7 относительно v5.\n")
    moved_up = 0
    total_young = 0
    for v, need, _ in needs:
        v5 = [s.candidate_id for s in rank(cands, need, TODAY, version=5)]
        r7 = rank(cands, need, TODAY, version=7)
        v7 = [s.candidate_id for s in r7]
        if not v7:
            continue

        def rub(x: int) -> str:
            return f"{x:,}".replace(",", " ")

        if need.salary_from and need.salary_to:
            sal = f"{rub(need.salary_from)}–{rub(need.salary_to)} ₽"
        elif need.salary_from:
            sal = f"от {rub(need.salary_from)} ₽"
        else:
            sal = "вилка не указана"
        w(
            f"### {v['title']} ({cat.specializations[need.specialization].name} · {cat.grade(need.grade).name}, {sal})\n"
        )
        w(f"[Источник]({v['source']})\n")

        def name(cid: str) -> str:
            return f"**{cid}**" if _young_fsp(by_id[cid]) else cid

        def shift(cid: str, v5: list[str] = v5, v7: list[str] = v7) -> str:
            d = v5.index(cid) - v7.index(cid)
            return f" ↑{d}" if d > 0 else (f" ↓{-d}" if d < 0 else "")

        w("v5: " + " → ".join(name(c) for c in v5))
        w("")
        w("v7: " + " → ".join(name(c) + shift(c) for c in v7))
        w("")
        for c in v7:
            if _young_fsp(by_id[c]):
                total_young += 1
                moved_up += v7.index(c) < v5.index(c)
        top = next((s for s in r7 if _young_fsp(by_id[s.candidate_id])), None)
        if top:
            reasons = "; ".join(r.text for r in top.reasons if "ФСП" in r.text or "опыт" in r.text.lower())
            w(f"> {top.candidate_id} в v7 — {v7.index(top.candidate_id) + 1}-е место: {reasons}\n")
    w("## Итог\n")
    w(
        f"Участники ФСП со стажем меньше года появились в выдаче {total_young} раз; в v7 они поднялись относительно v5 в "
        f"{moved_up} случаях из {total_young}. Кандидаты с опытом и сильным тестом остаются наверху, если стек совпадает: "
        "v7 не меняет «ворота» основного стека и вес теста (тест ≥ ФСП в силе профиля).\n"
    )
    return "\n".join(L)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default="docs", type=Path)
    path = p.parse_args().out / "bench3-results.md"
    path.write_text(report(), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
