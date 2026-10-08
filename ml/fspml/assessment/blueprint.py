"""Персональный состав теста: ядро специализации + модули заявленного стека.

Раньше состав был общим для специализации, а стек выбирал только язык — и при отсутствии
совпадения подставлялся Python: Java-, Go- и C#-разработчики получали пятую часть теста по чужому
языку, Vue-разработчики — задания по React, Linux-администраторы — по Kubernetes. Такие задания
измеряют не грейд, а знакомство с чужим стеком (construct-irrelevant variance) и систематически
занижают оценку.

Теперь:
* **ядро** (фундамент специализации) проверяется у всех — грейды в категории сопоставимы;
* **модули** — навыки, которые подтверждают заявленные технологии: тест проверяет то, что
  кандидат о себе заявил, и не проверяет того, чего он не заявлял;
* технологии без заданий в банке (Rust, Ruby, Kafka вне ядра) ничем не подменяются и остаются
  в профиле «заявленными»;
* **направление** внутри специализации (CV, NLP, рекомендации, временные ряды для DS), выбранное
  в опросе, входит модулем с приоритетом над стеком: CV-инженер получает задания по зрению, даже
  если не перечислил OpenCV.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Container, Iterable
from dataclasses import dataclass, field

from ..catalog import Catalog, get_catalog
from ..nlp.skills import SkillDictionary, get_dictionary

DIRECTION_BONUS = 2  # направление весит как две заявленные технологии: выигрывает у стека при отборе модулей


@dataclass(frozen=True)
class TestBlueprint:
    specialization: str
    weights: dict[str, float]  # навык → доля теста (сумма 1)
    core: tuple[str, ...]
    modules: dict[str, tuple[str, ...]]  # навык-модуль → технологии стека, из которых он выведен
    via_core: dict[str, tuple[str, ...]] = field(default_factory=dict)  # навык ядра → заявленные технологии
    untested: tuple[str, ...] = ()  # заявленные технологии, которых нет ни в ядре, ни в модулях

    def explanation(self, catalog: Catalog | None = None) -> list[str]:
        cat = catalog or get_catalog()
        title = lambda s: cat.assessment_skills.get(s, {}).get("title", s)  # noqa: E731
        spec = cat.specializations[self.specialization]
        lines = [
            f"Ядро специализации {spec.name} — у всех кандидатов категории, чтобы грейды были сопоставимы: "
            + ", ".join(title(s) for s in self.core)
            + "."
        ]
        in_modules = {t for src in self.modules.values() for t in src}
        via_core = [
            t for t in dict.fromkeys(t for src in self.via_core.values() for t in src) if t not in in_modules
        ]
        if self.modules:
            by_direction = any(t.startswith("направление") for src in self.modules.values() for t in src)
            lines.append(
                ("Модули по направлению и стеку: " if by_direction else "Модули по вашему стеку: ")
                + "; ".join(f"{title(s)} ({', '.join(src)})" for s, src in self.modules.items())
                + "."
            )
        elif via_core:
            lines.append("Отдельных модулей нет: заявленный стек проверяется заданиями ядра.")
        else:
            lines.append("Модулей нет: в заявленном стеке нет технологий, по которым есть задания.")
        if via_core:
            lines.append(f"Через ядро проверяются и заявленные {', '.join(via_core)}.")
        if self.untested:
            lines.append(
                "Без отдельных заданий: "
                + ", ".join(self.untested)
                + ". Чужие технологии вместо них не подставляются — в профиле они остаются заявленными."
            )
        return lines


def stack_evidence(stack: Iterable[str], dic: SkillDictionary | None = None) -> dict[str, list[str]]:
    """Навык теста → технологии стека, которые его подтверждают.

    Элемент стека — каноническое имя технологии («Django»), её алиас («джанго» не обязателен,
    но «postgres» найдётся) или id навыка теста («python»).
    """
    dic = dic or get_dictionary()
    skills = get_catalog().assessment_skills
    out: dict[str, list[str]] = {}
    for item in stack:
        item = str(item).strip()
        if not item:
            continue
        techs = [item] if item in dic.techs else list(dic.extract(item, fuzzy=False))
        if not techs and item.lower() in skills:
            out.setdefault(item.lower(), []).append(item)
            continue
        for t in techs:
            for s in dic.techs[t].assess:
                if t not in out.setdefault(s, []):
                    out[s].append(t)
    return out


def personal_blueprint(
    spec_id: str,
    stack: Iterable[str] = (),
    *,
    directions: Iterable[str] = (),
    available: Container[str] | None = None,
    catalog: Catalog | None = None,
) -> TestBlueprint:
    cat = catalog or get_catalog()
    dic = get_dictionary()
    spec = cat.specializations[spec_id]
    stack = list(dict.fromkeys(str(s).strip() for s in stack if str(s).strip()))
    ev = stack_evidence(stack, dic)
    counts = Counter({s: len(v) for s, v in ev.items()})
    for d in directions:
        skill = spec.direction_skill(d)
        if skill:
            title = next(x["title"] for x in spec.directions if x["id"] == d)
            ev.setdefault(skill, []).insert(0, f"направление «{title}»")
            counts[skill] += DIRECTION_BONUS
    weights = cat.blueprint(spec_id, counts, available)
    modules = {s: tuple(ev[s]) for s in weights if s not in spec.core}
    via_core = {s: tuple(ev[s]) for s in spec.core if s in ev}
    covered = {t for s in weights for t in ev.get(s, ())}
    untested = []
    for item in stack:
        techs = [item] if item in dic.techs else list(dic.extract(item, fuzzy=False))
        if not techs:
            if item.lower() not in cat.assessment_skills:
                untested.append(item)  # технология вне словаря: заданий по ней нет
        elif not any(t in covered for t in techs):
            untested.append(item)
    return TestBlueprint(
        specialization=spec_id,
        weights=weights,
        core=tuple(spec.core),
        modules=modules,
        via_core=via_core,
        untested=tuple(untested),
    )
