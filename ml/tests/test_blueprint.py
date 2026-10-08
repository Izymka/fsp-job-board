"""Персональный состав теста: ядро специализации + модули заявленного стека."""

from __future__ import annotations

import random

import pytest
from fspml.assessment.cat import Response, coverage_gap
from fspml.assessment.engine import AssessmentEngine
from fspml.assessment.irt import prob
from fspml.catalog import get_catalog
from fspml.nlp.skills import get_dictionary

ENGINE = AssessmentEngine(b"test-secret")


def weights(spec: str, stack: list[str]) -> dict[str, float]:
    return ENGINE.blueprint_for(spec, stack).weights


@pytest.mark.parametrize(
    "spec,stack,foreign",
    [
        ("backend", ["Java", "Spring", "PostgreSQL", "Kafka", "Docker"], {"python", "javascript"}),
        ("backend", ["Go", "PostgreSQL", "gRPC"], {"python", "javascript"}),
        ("frontend", ["Vue", "JavaScript", "CSS", "HTML"], {"react", "typescript"}),
        ("devops", ["Linux", "Ansible", "Bash", "Nginx"], {"kubernetes"}),
        ("qa", ["Selenium", "Java", "Postman"], {"python"}),
    ],
)
def test_no_skills_outside_declared_stack(spec, stack, foreign):
    """Чужой язык или фреймворк не подставляется: Java-разработчик не получает Python и т. п."""
    bp = weights(spec, stack)
    assert not foreign & set(bp), f"{spec} {stack}: в тесте чужие навыки {foreign & set(bp)}"
    assert set(get_catalog().specializations[spec].core) <= set(bp), "ядро проверяется всегда"


def test_language_without_tasks_is_reported_not_replaced():
    tb = ENGINE.blueprint_for("backend", ["Rust", "Docker"])
    assert "Rust" in tb.untested and "python" not in tb.weights
    assert any("Rust" in line for line in tb.explanation())


def test_stack_languages_get_own_modules():
    """Java, Go, C#, PHP и Vue проверяются заданиями на своём языке, а не подменяются Python/React."""
    cases = {
        ("backend", ("Java", "Spring", "Docker")): "java",
        ("backend", ("Go", "Gin")): "go",
        ("backend", ("C#", "PostgreSQL")): "csharp",
        ("backend", ("PHP", "Laravel")): "php",
        ("frontend", ("Vue", "TypeScript")): "vue",
    }
    for (spec, stack), skill in cases.items():
        tb = ENGINE.blueprint_for(spec, list(stack))
        assert skill in tb.modules and stack[0] in tb.modules[skill], (stack, tb.modules)
        assert not tb.untested and "python" not in tb.weights and "react" not in tb.weights


def test_modules_follow_stack_and_core_keeps_majority():
    cat = get_catalog()
    everything = list(get_dictionary().techs)  # максимально широкий заявленный стек
    for spec in cat.specializations.values():
        bp = weights(spec.id, everything)
        modules = [s for s in bp if s not in spec.core]
        assert abs(sum(bp.values()) - 1) < 1e-9
        assert len(modules) <= cat.raw["blueprint_rules"]["max_modules"]
        assert sum(bp[s] for s in spec.core) >= 0.6 - 1e-9, f"{spec.id}: ядро меньше 60%"
    py = weights("backend", ["Python", "Django", "FastAPI", "Docker", "Git"])
    assert py["python"] > py["docker"] == py["git"], "язык с фреймворками весит больше Git"
    assert weights("backend", []) == weights("backend", ["Rust"]) == cat.blueprint("backend")


def test_skill_ids_are_accepted_as_stack_items():
    assert "python" in weights("backend", ["python"])


def test_every_blueprint_skill_gets_at_least_two_items():
    """Сильный кандидат останавливается рано, но каждый навык состава получает ≥ 2 заданий —
    иначе его подоценка «нет данных» и бесполезна для подбора."""
    stack = ["Python", "Django", "Docker", "Git", "Kubernetes"]
    plan = ENGINE.plan_for_specialization("backend", "junior", stack)
    assert len(plan.blueprint) == 7
    rng = random.Random(5)
    for k in range(10):
        responses: list[Response] = []
        while (issued := ENGINE.next_item(f"cov{k}", plan, responses)) is not None:
            f = issued.family
            responses.append(ENGINE.response(f.id, rng.random() < float(prob(2.0, f.a, f.b, f.c))))
        counts = {s: sum(r.skill == s for r in responses) for s in plan.blueprint}
        assert min(counts.values()) >= 2, counts
        res = ENGINE.finish(plan, responses)
        assert all(s.status != "no_data" for s in res.skills.values())


def test_coverage_requirement_is_capped_by_bank():
    plan = ENGINE.plan_for_specialization("backend", "middle", ["Docker"])
    bank = [f for f in ENGINE.bank.values() if f.skill != "docker"]
    assert "docker" in coverage_gap([], plan)
    assert "docker" not in coverage_gap([], plan, bank)  # семейств нет — тест не тянется до max_items
