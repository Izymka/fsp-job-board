"""Справочники платформы (специализации, грейды, навыки, ФСП) из `data/catalog.yaml`."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class Grade:
    id: str
    name: str
    title: str
    experience: str
    cut: float
    order: int


@dataclass(frozen=True)
class Specialization:
    id: str
    name: str
    title: str
    description: str
    blueprint: dict[str, float]
    stack_languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class Catalog:
    grades: tuple[Grade, ...]
    specializations: dict[str, Specialization]
    assessment_skills: dict[str, dict]
    industries: tuple[dict, ...]
    work_formats: tuple[dict, ...]
    search_statuses: tuple[dict, ...]
    decline_reasons: tuple[dict, ...]
    fsp: dict
    raw: dict = field(repr=False, default_factory=dict)

    # --- грейды ---
    def grade(self, grade_id: str) -> Grade:
        for g in self.grades:
            if g.id == grade_id:
                return g
        raise KeyError(f"unknown grade: {grade_id}")

    def grade_index(self, grade_id: str) -> int:
        return self.grade(grade_id).order

    def grade_by_index(self, idx: int) -> Grade | None:
        if 0 <= idx < len(self.grades):
            return self.grades[idx]
        return None

    @property
    def cuts(self) -> list[float]:
        return [g.cut for g in self.grades]

    def grade_for_theta(self, theta: float) -> Grade:
        """Максимальный грейд, порог которого не выше θ (Intern — минимум)."""
        best = self.grades[0]
        for g in self.grades:
            if theta >= g.cut:
                best = g
        return best

    # --- blueprint ---
    def blueprint(self, spec_id: str, stack: list[str] | None = None) -> dict[str, float]:
        """Доли навыков в тесте специализации; `$language` раскрывается по стеку кандидата."""
        spec = self.specializations[spec_id]
        stack_l = {s.lower() for s in (stack or [])}
        bp: dict[str, float] = {}
        for skill, w in spec.blueprint.items():
            if skill == "$language":
                lang = next((x for x in spec.stack_languages if x in stack_l), None)
                lang = lang or (spec.stack_languages[0] if spec.stack_languages else None)
                if lang:
                    bp[lang] = bp.get(lang, 0.0) + w
            else:
                bp[skill] = bp.get(skill, 0.0) + w
        total = sum(bp.values())
        return {k: v / total for k, v in bp.items()}

    def fsp_weight(self, kind: str, item_id: str) -> float:
        for x in self.fsp[kind]:
            if x["id"] == item_id:
                return float(x["weight"])
        return 0.0

    def fsp_relevance(self, discipline: str, spec_id: str) -> float:
        for d in self.fsp["disciplines"]:
            if d["id"] == discipline:
                return float(d["relevance"].get(spec_id, 0.3))
        return 0.3


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    raw = yaml.safe_load((DATA_DIR / "catalog.yaml").read_text(encoding="utf-8"))
    grades = tuple(
        Grade(order=i, **{k: g[k] for k in ("id", "name", "title", "experience", "cut")})
        for i, g in enumerate(raw["grades"])
    )
    specs = {
        s["id"]: Specialization(
            id=s["id"],
            name=s["name"],
            title=s["title"],
            description=s["description"],
            blueprint=dict(s["blueprint"]),
            stack_languages=tuple(s.get("stack_languages", [])),
        )
        for s in raw["specializations"]
    }
    return Catalog(
        grades=grades,
        specializations=specs,
        assessment_skills={s["id"]: s for s in raw["assessment_skills"]},
        industries=tuple(raw["industries"]),
        work_formats=tuple(raw["work_formats"]),
        search_statuses=tuple(raw["search_statuses"]),
        decline_reasons=tuple(raw["decline_reasons"]),
        fsp=raw["fsp"],
        raw=raw,
    )
