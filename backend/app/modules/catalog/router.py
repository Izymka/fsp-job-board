from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter
from fspml.assessment.bank import REGISTRY
from fspml.catalog import get_catalog
from fspml.nlp.skills import get_dictionary
from pydantic import BaseModel

router = APIRouter(tags=["Справочники"])


class CatalogOut(BaseModel):
    grades: list[dict]
    specializations: list[dict]
    assessment_skills: list[dict]
    industries: list[dict]
    work_formats: list[dict]
    search_statuses: list[dict]
    decline_reasons: list[dict]
    fsp: dict
    technologies: list[dict]
    bank: dict


@lru_cache(maxsize=1)
def _catalog() -> CatalogOut:
    cat = get_catalog()
    dic = get_dictionary()
    by_skill: dict[str, int] = {}
    for f in REGISTRY.values():
        by_skill[f.skill] = by_skill.get(f.skill, 0) + 1
    return CatalogOut(
        grades=[
            {"id": g.id, "name": g.name, "title": g.title, "experience": g.experience, "order": g.order}
            for g in cat.grades
        ],
        specializations=[
            {
                "id": s.id,
                "name": s.name,
                "title": s.title,
                "description": s.description,
                # состав теста без заявленного стека (только ядро); персональный — /api/assessment/eligibility
                "blueprint": cat.blueprint(s.id),
                "core": list(s.core),
                "modules": list(s.modules),
                "skills": list(s.skills),
                "directions": list(s.directions),
            }
            for s in cat.specializations.values()
        ],
        assessment_skills=[{**v, "families": by_skill.get(k, 0)} for k, v in cat.assessment_skills.items()],
        industries=list(cat.industries),
        work_formats=list(cat.work_formats),
        search_statuses=list(cat.search_statuses),
        decline_reasons=list(cat.decline_reasons),
        fsp=cat.fsp,
        technologies=[
            {"name": t.name, "assess": list(t.assess), "specializations": t.spec}
            for t in sorted(dic.techs.values(), key=lambda t: t.name.lower())
        ],
        bank={"families": len(REGISTRY), "by_skill": by_skill},
    )


@router.get(
    "/api/catalog",
    response_model=CatalogOut,
    summary="Справочники: специализации, грейды, навыки, отрасли, ФСП",
)
def catalog():
    return _catalog()


@router.get(
    "/api/catalog/demo-vacancies", summary="Демонстрационные описания вакансий (для показа генерации тестов)"
)
def demo_vacancies():
    import yaml
    from fspml.catalog import DATA_DIR

    data = yaml.safe_load((DATA_DIR / "vacancies.yaml").read_text(encoding="utf-8"))["vacancies"]
    return [{k: v[k] for k in ("id", "company", "industry", "title", "text")} for v in data]


@router.get(
    "/api/catalog/validation", summary="Сводка результатов валидации механик (генерируется make validate)"
)
def validation_summary():
    import json

    from fspml.catalog import DATA_DIR

    p = DATA_DIR / "validation_summary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
