"""Механика v5: специфичность требований и «ворота» поверх формулы v1."""

from __future__ import annotations

from fspml.matching.scoring import Need, rank, specificity
from test_matching_nlp import TODAY, cand

GO_NEED = Need(
    specialization="backend",
    grade="middle",
    skills={"Go": 1.0, "PostgreSQL": 1.0, "Docker": 1.0, "Git": 1.0, "Kafka": 1.0, "Redis": 0.45},
    salary_from=250_000,
    salary_to=330_000,
    work_format="remote",
)


def pool():
    """Типичная категория: Docker, Git, PostgreSQL есть почти у всех, Go — у немногих."""
    common = {"Docker", "Git", "PostgreSQL"}
    fillers = [cand(f"f{i}", claimed=common | {"Python", "Django"}, theta=0.2) for i in range(12)]
    java = cand("java", claimed=common | {"Java", "Spring", "Kafka", "Redis"}, theta=0.9)
    go = cand("go", claimed={"Go", "PostgreSQL", "Kafka"}, theta=0.3)
    return [*fillers, java, go]


def test_specificity_downweights_commodity_requirements():
    w = specificity(pool(), GO_NEED.skills)
    assert w["Go"] > w["Kafka"] > w["Docker"] == w["Git"]
    assert w["PostgreSQL"] < w["Docker"]  # есть даже у Go-разработчика


def test_primary_language_beats_commodity_overlap():
    """v1 ставит сильного Java-разработчика с Docker/Git/Kafka выше Go-разработчика на Go-вакансию;
    v5 — нет: Go определяет стек вакансии, а Docker и Git есть у всех."""
    v1 = [s.candidate_id for s in rank(pool(), GO_NEED, TODAY, version=1)]
    v5 = rank(pool(), GO_NEED, TODAY)
    assert v1.index("java") < v1.index("go")
    ids = [s.candidate_id for s in v5]
    assert ids[0] == "go" and ids.index("go") < ids.index("java")
    java = next(s for s in v5 if s.candidate_id == "java")
    assert java.details["gate_must"] < 1.0
    assert any(r.text.startswith("Не закрыто из обязательного: Go") for r in java.reasons)


def test_gates_explain_conditions():
    far = cand("far", claimed={"Go", "PostgreSQL", "Kafka", "Docker"}, salary_from=600_000)
    office = cand("office", claimed={"Go", "PostgreSQL", "Kafka", "Docker"}, work_formats={"office"})
    ok = cand("ok", claimed={"Go", "PostgreSQL", "Kafka", "Docker"})
    res = {s.candidate_id: s for s in rank([*pool(), far, office, ok], GO_NEED, TODAY)}
    assert res["far"].details["gate_salary"] < 0.6
    assert any("выше вилки более чем на 15%" in r.text for r in res["far"].reasons)
    assert res["office"].details["gate_format"] < 0.5
    assert res["ok"].score > max(res["far"].score, res["office"].score)
    assert abs(sum(res["ok"].components.values()) - res["ok"].score) < 1e-3
