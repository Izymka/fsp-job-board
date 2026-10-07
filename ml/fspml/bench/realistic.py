"""Реалистичный бенчмарк (bench2): живые тексты резюме и вакансий по скрытым профилям.

Отличия от первого бенчмарка:
* стеки кандидатов и вакансий сэмплируются из архетипов (`data/stack_archetypes.yaml`) — в них
  есть реальные связки технологий и «смежные, но не те» стеки;
* тексты резюме и вакансий пишут агенты-LLM офлайн по брифу со скрытым профилем (без ПДн:
  кандидаты вымышленные, имён и контактов нет);
* «Заявленный стек» в карточке платформы получается **разбором текста резюме нашим NLP**,
  а не берётся из генератора — проверяется весь конвейер, включая разбор резюме.

Бриф содержит скрытую истину (реальный стек, «накрученные» технологии) — его видят только
агенты-писатели, асессорам он недоступен.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from ..catalog import get_catalog
from ..validation.population import make_candidates, make_needs

ROOT = Path(__file__).resolve().parents[2] / "bench2"
BRIEFS = ROOT / "briefs"
TEXTS = ROOT / "texts"
N_CANDIDATES = 700
N_NEEDS = 30
CITIES = [
    "Москва",
    "Санкт-Петербург",
    "Казань",
    "Новосибирск",
    "Екатеринбург",
    "Нижний Новгород",
    "Томск",
    "Самара",
    "Пермь",
    "Краснодар",
]
FORMAT_RU = {"office": "офис", "hybrid": "гибрид", "remote": "удалённо"}


def population():
    return make_candidates(N_CANDIDATES, seed=17, stuffing_rate=0.3, realistic=True), make_needs(
        N_NEEDS, seed=19, realistic=True
    )


def export_briefs(chunk: int = 100) -> list[Path]:
    cat = get_catalog()
    cands, needs = population()
    rng = random.Random(5)
    BRIEFS.mkdir(parents=True, exist_ok=True)
    paths = []
    for k in range(0, len(cands), chunk):
        rows = []
        for c in cands[k : k + chunk]:
            rows.append(
                {
                    "cand_id": c.id,
                    "specialization": cat.specializations[c.spec].title,
                    "self_title_grade": cat.grade(c.claimed_grade).name,
                    "years_experience": round(c.years, 1),
                    "real_stack": sorted(c.techs),
                    "stuffed_stack": sorted(c.stuffed),
                    "salary_from_rub": c.salary_from,
                    "work_formats": [FORMAT_RU[f] for f in sorted(c.work_formats)],
                    "city": rng.choice(CITIES),
                    "style": rng.choice(["список", "проза", "кратко", "подробно", "смешанно"]),
                }
            )
        p = BRIEFS / f"cands_{k // chunk + 1:02d}.jsonl"
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        paths.append(p)
    nrows = []
    for n in needs:
        nrows.append(
            {
                "need_id": n.id,
                "specialization": cat.specializations[n.spec].title,
                "grade": cat.grade(n.grade).name,
                "must": sorted(t for t, w in n.skills.items() if w >= 0.6),
                "plus": sorted(t for t, w in n.skills.items() if w < 0.6),
                "salary_from_rub": n.salary_from,
                "salary_to_rub": n.salary_to,
                "work_format": FORMAT_RU[n.work_format],
                "industry": next(x["title"] for x in cat.industries if x["id"] == n.industry),
            }
        )
    p = BRIEFS / "needs.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in nrows), encoding="utf-8")
    paths.append(p)
    return paths


def _load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def prepare():
    """Популяция bench2: признаки кандидатов из текста резюме (наш NLP), вакансии — из живых текстов."""
    from dataclasses import replace

    from ..nlp.embed import HashingEmbedder
    from ..nlp.skills import get_dictionary
    from ..nlp.vacancy import parse_need
    from ..validation import matching as vm
    from ..validation.assessment import make_true_bank
    from . import systems as S
    from .build import _to_need
    from .dossier import render_need

    cands, tneeds = population()
    resumes = {r["cand_id"]: r["text"] for p in sorted(TEXTS.glob("resumes_*.jsonl")) for r in _load(p)}
    vac = {r["need_id"]: r for r in _load(TEXTS / "vacancies.jsonl")}
    missing = [c.id for c in cands if c.id not in resumes]
    if missing:
        raise RuntimeError(f"нет текстов резюме для {len(missing)} кандидатов, например {missing[:3]}")
    dic, emb = get_dictionary(), HashingEmbedder()
    feats = []
    for f in vm.observe(cands, make_true_bank(), legacy=True).features:
        text = resumes[f.id]
        feats.append(replace(f, claimed=set(dic.extract(text)), about=text, embedding=emb.encode([text])[0]))
    needs = []
    for tn in tneeds:
        v = vac[tn.id]
        pn = parse_need(v["text"], v["title"])
        needs.append(
            S.BenchNeed(
                tn.id,
                "synthetic",
                v["title"],
                render_need(v["title"], v["text"], v.get("company")),
                _to_need(pn, v["text"], tn.industry),
                {"true_spec": tn.spec, "true_grade": tn.grade},
            )
        )
    return cands, feats, needs, {tn.id: tn for tn in tneeds}


def parse_quality() -> dict:
    """Качество разбора живых текстов нашим NLP против скрытой истины генератора."""
    from ..nlp.skills import get_dictionary
    from ..nlp.vacancy import parse_need

    cands, tneeds = population()
    resumes = {r["cand_id"]: r["text"] for p in sorted(TEXTS.glob("resumes_*.jsonl")) for r in _load(p)}
    vac = {r["need_id"]: r for r in _load(TEXTS / "vacancies.jsonl")}
    dic = get_dictionary()
    tp = fp = fn = 0
    for c in cands:
        got, want = set(dic.extract(resumes[c.id])), c.techs | c.stuffed
        tp, fp, fn = tp + len(got & want), fp + len(got - want), fn + len(want - got)
    spec_ok = grade_ok = 0
    mtp = mfp = mfn = 0
    for tn in tneeds:
        pn = parse_need(vac[tn.id]["text"], vac[tn.id]["title"])
        spec_ok += pn.specialization == tn.spec
        grade_ok += pn.grade == tn.grade
        got, want = set(pn.skills), set(tn.skills)
        mtp, mfp, mfn = mtp + len(got & want), mfp + len(got - want), mfn + len(want - got)

    def prf(a, b, c):
        p, r = a / max(1, a + b), a / max(1, a + c)
        return {"precision": p, "recall": r, "f1": 2 * p * r / max(1e-9, p + r)}

    return {
        "resume_tech": prf(tp, fp, fn),
        "vacancy_tech": prf(mtp, mfp, mfn),
        "vacancy_spec_accuracy": spec_ok / len(tneeds),
        "vacancy_grade_accuracy": grade_ok / len(tneeds),
        "n_resumes": len(cands),
        "n_vacancies": len(tneeds),
    }


def build2(neural: bool = True) -> dict:
    from .build import build

    return build(prepared=prepare(), out=ROOT / "data", neural=neural)
