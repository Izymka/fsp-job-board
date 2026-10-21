"""Механика v7: весомый ФСП и достижения ФСП как опыт работы поверх v6."""

from __future__ import annotations

from datetime import date

from fspml.matching.scoring import (
    DEFAULT_WEIGHTS,
    WEIGHTS_V7,
    FspAchievement,
    Need,
    experience_fit,
    fsp_strength,
    rank,
)
from test_matching_nlp import TODAY, cand

PRIZE = [FspAchievement("product", "national", "prize", date(2026, 5, 1))]

JUNIOR_NEED = Need(
    specialization="backend",
    grade="junior",
    skills={"Python": 1.0, "PostgreSQL": 1.0, "FastAPI": 0.8},
    salary_from=90_000,
    salary_to=140_000,
    work_format="remote",
)


def junior(cid: str, **kw):
    base = dict(
        grade="junior",
        theta=-0.6,
        salary_from=100_000,
        salary_to=120_000,
        experience_years=0.0,
        relevant_years=0.0,
        it_years=0.0,
    )
    base.update(kw)
    return cand(cid, **base)


def test_fsp_share_of_score_raised():
    assert DEFAULT_WEIGHTS.profile * DEFAULT_WEIGHTS.ps_fsp == 0.075
    assert WEIGHTS_V7.profile * WEIGHTS_V7.ps_fsp > 0.13
    assert WEIGHTS_V7.ps_fsp <= WEIGHTS_V7.ps_test  # тест остаётся главным в силе профиля


def test_fsp_counts_as_experience_for_junior():
    c = junior("talent", fsp=PRIZE)
    f = fsp_strength(c.fsp, c.specialization, TODAY)
    without, _ = experience_fit(c, JUNIOR_NEED)
    with_fsp, reasons = experience_fit(c, JUNIOR_NEED, fsp=f)
    assert without == 0.5 and with_fsp == 1.0
    assert any("Достижения ФСП засчитаны как практический опыт" in r.text for r in reasons)


def test_fsp_does_not_inflate_experience_above_requirement():
    """ФСП закрывает только нехватку стажа: у кандидата с опытом бонус не растёт."""
    c = junior("exp", relevant_years=1.0, it_years=1.0, experience_years=1.0, fsp=PRIZE)
    plain, _ = experience_fit(c, JUNIOR_NEED)
    boosted, reasons = experience_fit(c, JUNIOR_NEED, fsp=1.0)
    assert plain == boosted
    assert not any("ФСП" in r.text for r in reasons)


def test_fsp_barely_moves_senior_requirement():
    need = Need(specialization="backend", grade="senior", skills={"Python": 1.0})
    c = junior("young", grade="senior", fsp=PRIZE)
    without, _ = experience_fit(c, need)
    with_fsp, _ = experience_fit(c, need, fsp=fsp_strength(c.fsp, "backend", TODAY))
    assert with_fsp - without < 0.1


def test_young_fsp_talent_ranks_above_v5():
    """Участник ФСП без стажа и с чуть более слабым тестом: в v5 ниже кандидата с полугодом опыта, в v7 — выше."""
    talent = junior("talent", theta=-0.7, fsp=PRIZE)
    worker = junior("worker", theta=-0.5, relevant_years=0.5, it_years=0.5, experience_years=0.5)
    v5 = [s.candidate_id for s in rank([talent, worker], JUNIOR_NEED, TODAY, version=5)]
    v7 = [s.candidate_id for s in rank([talent, worker], JUNIOR_NEED, TODAY, version=7)]
    assert v5 == ["worker", "talent"]
    assert v7 == ["talent", "worker"]


def test_fsp_does_not_bypass_core_stack_gate():
    go_need = Need(
        specialization="backend",
        grade="junior",
        skills={"Go": 1.0, "PostgreSQL": 1.0},
        salary_from=90_000,
        salary_to=140_000,
        work_format="remote",
    )
    gopher = junior("go", claimed={"Go", "PostgreSQL"})
    champion = junior(
        "champ",
        claimed={"Python", "PostgreSQL"},
        fsp=[FspAchievement("product", "international", "winner", date(2026, 6, 1))],
    )
    res = {s.candidate_id: s for s in rank([gopher, champion], go_need, TODAY, version=7)}
    assert res["champ"].details["gate_core"] < 1.0
    assert res["go"].score > res["champ"].score


def test_no_fsp_history_is_not_penalized_vs_v6():
    c = junior("plain", fsp=None, relevant_years=1.0, it_years=1.0, experience_years=1.0)
    v6 = rank([c], JUNIOR_NEED, TODAY, version=6)[0]
    v7 = rank([c], JUNIOR_NEED, TODAY, version=7)[0]
    assert v7.details["gate_experience"] == v6.details["gate_experience"]
    assert any(r.text == "ФСП ID не привязан" for r in v7.reasons)


def test_fsp_friendly_vacancy_counts_fsp_up_to_requirement():
    """«Открыта для ФСП»: на Middle (от 2 лет) обычный потолок ФСП-опыта — 1 год, у такой вакансии — 2."""
    need = Need(specialization="backend", grade="middle", skills={"Python": 1.0}, min_years=2.0)
    friendly = Need(**{**need.__dict__, "fsp_friendly": True})
    c = junior(
        "champ", grade="middle", fsp=[FspAchievement("product", "international", "winner", date(2026, 6, 1))]
    )
    f = fsp_strength(c.fsp, "backend", TODAY)
    plain, _ = experience_fit(c, need, fsp=f)
    open_, reasons = experience_fit(c, friendly, fsp=f)
    assert open_ > plain
    assert any("Достижения ФСП засчитаны как практический опыт" in r.text for r in reasons)
    # без ФСП разницы нет: флаг не даёт преимущества кандидатам без достижений
    nobody = junior("plain", grade="middle")
    assert experience_fit(nobody, need)[0] == experience_fit(nobody, friendly)[0]
