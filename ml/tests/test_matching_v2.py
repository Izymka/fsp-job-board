"""Механика v2 (граф навыков, «ворота») и v3 (LambdaMART): ключевые свойства."""

from __future__ import annotations

from fspml.matching import ltr
from fspml.matching.scoring import Need, rank, score_candidate_v2, tech_credit
from fspml.nlp.vacancy import parse_need
from test_matching_nlp import TODAY, cand


def need(**kw) -> Need:
    base = dict(
        specialization="backend",
        grade="middle",
        skills={"Python": 1.0, "PostgreSQL": 1.0, "Kafka": 1.0, "Kubernetes": 0.45},
        salary_from=250_000,
        salary_to=330_000,
        work_format="office",
    )
    base.update(kw)
    return Need(**base)


def test_graph_gives_partial_credit():
    c = cand("a", claimed={"Python", "RabbitMQ"})
    value, src, via = tech_credit(c, "Kafka")
    assert src == "graph" and via == "RabbitMQ" and 0 < value < 0.6
    assert tech_credit(cand("b", claimed={"Python"}), "Kafka")[0] == 0.0


def test_incompatible_format_is_a_gate_not_a_small_penalty():
    office = cand("office", work_formats={"office"}, claimed={"Python", "PostgreSQL", "Kafka"})
    remote = cand("remote", work_formats={"remote"}, claimed={"Python", "PostgreSQL", "Kafka"})
    s_office = score_candidate_v2(office, need(), TODAY).score
    s_remote = score_candidate_v2(remote, need(), TODAY).score
    assert s_remote < 0.6 * s_office


def test_salary_gate_grows_with_gap():
    n = need()
    near = score_candidate_v2(cand("n", salary_from=360_000, work_formats={"office"}), n, TODAY)
    far = score_candidate_v2(cand("f", salary_from=700_000, work_formats={"office"}), n, TODAY)
    assert near.details["gate_salary"] == 1.0  # до 15% выше вилки — без штрафа
    assert far.details["gate_salary"] < 0.5
    assert any("выше вилки" in r.text for r in far.reasons)


def test_fsp_does_not_compensate_missing_must_skills():
    from fspml.matching.scoring import FspAchievement

    star = [FspAchievement("algorithms", "national", "winner", TODAY)]
    weak = cand("weak", claimed={"Go"}, skill_status={}, fsp=star, work_formats={"office"})
    fit = cand("fit", claimed={"Python", "PostgreSQL", "Kafka"}, fsp=None, work_formats={"office"})
    ranked = [s.candidate_id for s in rank([weak, fit], need(), TODAY, version=2)]
    assert ranked == ["fit", "weak"]


def test_components_sum_to_score():
    s = score_candidate_v2(cand("x", work_formats={"office"}), need(), TODAY)
    assert abs(sum(s.components.values()) - s.score) < 1e-3


def test_parse_need_is_deterministic_order():
    pn = parse_need("Требования: Python, Docker, Git, SQL.", "Backend Middle")
    assert list(pn.skills) == sorted(pn.skills, key=lambda k: (-pn.skills[k], k))


def test_ltr_monotone_in_test_and_salary():
    """Монотонные ограничения: лучше тест — не ниже балл; выше ожидания по ЗП — не выше балл."""
    booster = ltr.load()
    if booster is None:
        return  # модель не обучена в этой сборке
    import numpy as np

    base = {
        "must_coverage": 0.7,
        "plus_coverage": 0.5,
        "test": 0.5,
        "fsp": 0.0,
        "tasks": 0.0,
        "freshness": 1.0,
        "format_fit": 1.0,
        "salary_gap": 0.0,
        "grade_diff": 0.0,
        "active_search": 1.0,
    }
    grid = np.linspace(0, 1, 11)
    by_test = booster.predict(ltr.matrix([{**base, "test": t} for t in grid]))
    by_gap = booster.predict(ltr.matrix([{**base, "salary_gap": g} for g in grid]))
    assert all(np.diff(by_test) >= -1e-9)
    assert all(np.diff(by_gap) <= 1e-9)
