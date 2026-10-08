"""Справочники платформы (специализации, грейды, навыки, ФСП) из `data/catalog.yaml`."""

from __future__ import annotations

import math
from collections.abc import Container, Mapping
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
    core: dict[str, float]  # фундамент: проверяется у всех кандидатов категории
    modules: tuple[str, ...] = ()  # навыки стека: входят в тест, только если заявлены
    # направления внутри специализации (CV, NLP…): {id, title, skill?} — навык-модуль направления
    directions: tuple[dict, ...] = ()

    def direction_skill(self, direction_id: str) -> str | None:
        return next((d.get("skill") for d in self.directions if d["id"] == direction_id), None)

    @property
    def skills(self) -> tuple[str, ...]:
        return (*self.core, *self.modules)


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
    def blueprint(
        self,
        spec_id: str,
        evidence: Mapping[str, float] | None = None,
        available: Container[str] | None = None,
    ) -> dict[str, float]:
        """Доли навыков в тесте: ядро специализации + модули стека.

        evidence — навык теста → сколько заявленных технологий его подтверждают (Django и FastAPI
        дают python = 2). В модули попадают до `max_modules` навыков из `modules` специализации
        с наибольшей поддержкой; их доля — `module_share` на модуль, но не больше `module_share_max`,
        внутри — пропорционально √поддержки (язык с тремя фреймворками весит больше, чем Git).
        available — навыки, по которым в банке достаточно заданий (недоступные модули пропускаются).
        """
        spec = self.specializations[spec_id]
        rules = self.raw.get("blueprint_rules", {})
        ev = {
            s: float(v)
            for s, v in (evidence or {}).items()
            if v > 0 and s in spec.modules and s not in spec.core and (available is None or s in available)
        }
        chosen = sorted(ev, key=lambda s: (-ev[s], spec.modules.index(s)))[: int(rules.get("max_modules", 3))]
        share = min(
            float(rules.get("module_share_max", 0.4)), float(rules.get("module_share", 0.2)) * len(chosen)
        )
        core_total = sum(spec.core.values())
        bp = {k: (1 - share) * v / core_total for k, v in spec.core.items()}
        support = {s: math.sqrt(ev[s]) for s in chosen}
        for s in chosen:
            bp[s] = share * support[s] / sum(support.values())
        return bp

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
            core=dict(s["core"]),
            modules=tuple(s.get("modules", [])),
            directions=tuple(s.get("directions", [])),
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
