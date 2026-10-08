"""Механика v5: специфичность требований и «ворота» поверх формулы v1."""

from __future__ import annotations

import pytest
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


def test_trust_proctor_with_remarks_above_plain():
    """Одинаковые кандидаты: проктор даже с тяжёлыми замечаниями выше чистого теста без проктора."""
    from dataclasses import replace

    base = cand("x", claimed={"Go", "PostgreSQL", "Kafka", "Docker", "Git"}, theta=0.3)
    pool_ = [
        replace(base, id="plain", integrity="clean", integrity_severity="none"),
        replace(base, id="plain_rev", integrity="review", integrity_severity="soft"),
        replace(base, id="proc", proctored=True, integrity="clean", integrity_severity="none"),
        replace(base, id="proc_soft", proctored=True, integrity="review", integrity_severity="soft"),
        replace(base, id="proc_hard", proctored=True, integrity="review", integrity_severity="hard"),
    ]
    out = rank(pool_, GO_NEED, TODAY)
    assert [s.candidate_id for s in out] == ["proc", "proc_soft", "proc_hard", "plain", "plain_rev"]
    by = {s.candidate_id: s.score for s in out}
    for cid, ratio in (("proc_soft", 0.9), ("proc_hard", 0.8), ("plain", 0.6), ("plain_rev", 0.5)):
        assert by[cid] / by["proc"] == pytest.approx(ratio, abs=1e-3)
    reasons = {s.candidate_id: [r.text for r in s.reasons] for s in out}
    assert "Тест пройден с цифровым проктором" in reasons["proc"]
    assert any("без проктора" in t for t in reasons["plain"])


def test_trust_legacy_profiles_and_interrupted_proctor():
    """Профили без severity: review → мягкие замечания; прерванный проктор — как без проктора."""
    from dataclasses import replace

    from fspml.matching.scoring import trust_level

    base = cand("x", claimed={"Go"}, theta=0.3)
    assert trust_level(replace(base, proctored=True, integrity="review")) == "proctor_soft"
    assert trust_level(replace(base, integrity="review")) == "plain_review"
    assert trust_level(replace(base, integrity="ok")) == "plain_clean"
    # proctored=False у прерванного проктора (статус interrupted) — ярус «без проктора»
    assert trust_level(replace(base, proctored=False, integrity="clean")) == "plain_clean"
    assert trust_level(replace(base, theta=None)) is None


def test_much_better_fit_without_proctor_still_wins():
    strong = cand("strong", claimed={"Go", "PostgreSQL", "Kafka", "Docker", "Git"}, theta=0.6)
    weak = cand("weak", claimed={"Python", "Docker", "Git"}, theta=0.0, proctored=True)
    ids = [s.candidate_id for s in rank([strong, weak], GO_NEED, TODAY)]
    assert ids == ["strong", "weak"]


def test_experience_relative_to_vacancy_requirement():
    from dataclasses import replace

    from fspml.matching.scoring import experience_fit

    need = replace(GO_NEED, min_years=3.0)
    base = cand("x", claimed={"Go", "PostgreSQL"}, theta=0.3)
    f = lambda **kw: experience_fit(replace(base, **kw), need)[0]  # noqa: E731
    assert f() == pytest.approx(0.9)  # опыт не указан
    assert f(experience_years=0.0, relevant_years=0.0, it_years=0.0) == pytest.approx(0.5)
    assert f(experience_years=3.0, relevant_years=3.0, it_years=3.0) == pytest.approx(1.0)
    assert f(experience_years=7.0, relevant_years=7.0, it_years=7.0) == pytest.approx(1.06)
    # 5 лет в IT, но не в этой роли: засчитывается 30% → 1.5 года из 3
    assert f(experience_years=5.0, relevant_years=0.0, it_years=5.0) == pytest.approx(0.75)
    # стаж без разбивки по местам работы считается релевантным (заявлен кандидатом)
    assert f(experience_years=3.0) == pytest.approx(1.0)
    # опыт в отрасли вакансии
    ind = replace(need, industry="fintech")
    c = replace(base, experience_years=3.0, relevant_years=3.0, it_years=3.0, industry_years={"fintech": 2.0})
    fac, reasons = experience_fit(c, ind)
    assert fac == pytest.approx(1.04)
    assert any("отрасли" in r.text for r in reasons)


def test_relevant_experience_outranks_career_switcher():
    from dataclasses import replace

    need = replace(GO_NEED, min_years=3.0)
    base = cand("x", claimed={"Go", "PostgreSQL", "Kafka", "Docker", "Git"}, theta=0.3)
    pool_ = [
        replace(base, id="switcher", experience_years=6.0, relevant_years=1.0, it_years=6.0),
        replace(base, id="relevant", experience_years=4.0, relevant_years=4.0, it_years=4.0),
        replace(base, id="none", experience_years=0.0, relevant_years=0.0, it_years=0.0),
    ]
    out = rank(pool_, need, TODAY)
    assert [s.candidate_id for s in out] == ["relevant", "switcher", "none"]
    texts = {s.candidate_id: " ".join(r.text for r in s.reasons) for s in out}
    assert "Нет коммерческого опыта; требуется от 3 лет" in texts["none"]
    assert "Релевантный опыт: 1 год (всего в IT — 6 лет)" in texts["switcher"]


def test_summarize_jobs():
    from datetime import date

    from fspml.matching.experience import job_specialization, summarize

    assert job_specialization("Python-разработчик, Банк") == "backend"
    assert job_specialization("Аналитик данных") == "data_science"
    assert job_specialization("Менеджер по продажам") is None
    jobs = [
        {"title": "Python-разработчик", "start": "2021", "end": "2023", "industry": "fintech"},
        {"title": "Менеджер по продажам", "start": "2018", "end": "2020"},
        {"title": "Тестировщик", "start": "2024-01", "end": None, "industry": "ecommerce"},
    ]
    s = summarize(jobs, "backend", date(2026, 1, 1))
    assert s.relevant_years == 3.0
    assert s.total_years == pytest.approx(3 + 3 + 2.1, abs=0.1)
    assert s.it_years == pytest.approx(5.1, abs=0.1)
    assert s.industry_years["fintech"] == 3.0
