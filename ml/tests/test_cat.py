from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import pytest
from fspml.assessment import grade_policy as gp
from fspml.assessment.calibration import calibrate
from fspml.assessment.cat import CatPlan
from fspml.assessment.drift import run_cusum
from fspml.assessment.engine import AssessmentEngine
from fspml.assessment.irt import GRID, ItemParams, posterior, prob
from fspml.catalog import get_catalog

ENGINE = AssessmentEngine(b"test-secret")


def simulate(theta: float, plan: CatPlan, attempt: str, rng: random.Random):
    responses = []
    while (issued := ENGINE.next_item(attempt, plan, responses)) is not None:
        p = float(prob(theta, issued.family.a, issued.family.b, issued.family.c))
        responses.append(ENGINE.response(issued.family.id, rng.random() < p))
    return ENGINE.finish(plan, responses), responses


def test_posterior_is_monotone_in_correct_answers():
    item = ItemParams(1.3, 0.0, 0.0)
    lo = posterior([(item, False)] * 5).mean
    hi = posterior([(item, True)] * 5).mean
    assert lo < 0 < hi
    assert posterior([]).prob_above(0.0) == pytest.approx(0.5, abs=0.01)
    assert abs(sum(posterior([(item, True)]).weights) - 1) < 1e-9
    assert GRID[0] == -4


def test_cat_respects_length_limits_and_blueprint():
    plan = ENGINE.plan_for_specialization("backend", "middle", ["python"])
    res, responses = simulate(0.3, plan, "a1", random.Random(1))
    cfg = plan.config
    assert cfg.min_items <= res.n_items <= cfg.max_items
    assert len({r.family_id for r in responses}) == len(responses), "семейства не повторяются в попытке"
    assert {r.skill for r in responses} <= set(plan.blueprint)


def test_seen_families_are_avoided_across_attempts():
    """DS: Junior, затем Middle — второй тест идёт на других семействах, пока в навыке есть новые."""
    rng = random.Random(3)
    first_plan = ENGINE.plan_for_specialization("data_science", "junior", ["pandas", "sql"])
    _, first = simulate(-0.5, first_plan, "ds-1", rng)
    seen = frozenset(r.family_id for r in first)
    plan = replace(ENGINE.plan_for_specialization("data_science", "middle", ["pandas", "sql"]), seen=seen)
    _, second = simulate(-0.5, plan, "ds-2", rng)
    repeated = {r.family_id for r in second} & seen
    assert not repeated, f"повторились семейства: {repeated}"


def test_seen_falls_back_when_skill_exhausted():
    """Если все семейства навыка уже видены, тест не обрывается, а берёт увиденные."""
    plan = ENGINE.plan_for_specialization("backend", "middle")
    seen = frozenset(f.id for f in ENGINE.bank.values())
    _, responses = simulate(0.0, replace(plan, seen=seen), "all-seen", random.Random(5))
    assert len(responses) >= plan.config.min_items


def test_group_siblings_not_issued_together():
    """Семейства одной группы (GROUP BY в SQL и groupby в pandas) — один вопрос; в попытке не больше одного."""
    plan = ENGINE.plan_for_specialization("data_science", "middle", ["pandas", "sql", "metrics"])
    for i in range(20):
        _, responses = simulate(0.0, plan, f"grp-{i}", random.Random(i))
        groups = [ENGINE.bank[r.family_id].group for r in responses if ENGINE.bank[r.family_id].group]
        assert len(groups) == len(set(groups)), groups


@pytest.mark.parametrize("spec", ["backend", "frontend", "data_science", "qa", "devops", "analyst", "mobile"])
def test_cat_classifies_clear_cases(spec):
    cat = get_catalog()
    rng = random.Random(42)
    plan = ENGINE.plan_for_specialization(spec, "middle")
    cut = cat.grade("middle").cut
    strong = [simulate(cut + 1.2, plan, f"s{i}", rng)[0].decision for i in range(15)]
    weak = [simulate(cut - 1.2, plan, f"w{i}", rng)[0].decision for i in range(15)]
    assert strong.count("confirmed") >= 13
    assert weak.count("not_confirmed") >= 13


def test_instance_regeneration_matches_issued():
    plan = ENGINE.plan_for_specialization("frontend", "junior")
    issued = ENGINE.next_item("att-77", plan, [])
    again = ENGINE.regenerate("att-77", issued.position, issued.family.id)
    assert again.prompt == issued.instance.prompt and again.answer == issued.instance.answer
    # другой кандидат на той же позиции получает другой экземпляр
    other = ENGINE.next_item("att-78", plan, [])
    assert (other.family.id, other.instance.prompt) != (issued.family.id, issued.instance.prompt)


def test_skill_scores_have_statuses():
    plan = ENGINE.plan_for_specialization("data_science", "middle")
    res, _ = simulate(1.5, plan, "sk", random.Random(3))
    assert res.skills
    assert all(s.status in {"confirmed", "uncertain", "weak", "no_data"} for s in res.skills.values())


def test_grade_policy_onboarding_and_cooldowns():
    t0 = datetime(2026, 10, 5)
    st = gp.GradeState()
    st = gp.start_attempt(st, "middle", t0)
    assert not gp.check_attempt(st, "junior", t0).allowed  # активная попытка
    st, ev = gp.finish_attempt(st, False, t0)
    assert ev is None
    # после неудачи на Middle — Junior сразу, Middle/Senior — через 14 дней
    assert gp.check_attempt(st, "junior", t0).allowed
    blocked = gp.check_attempt(st, "senior", t0)
    assert not blocked.allowed and blocked.available_at == t0 + timedelta(days=14)
    st = gp.start_attempt(st, "junior", t0)
    st, ev = gp.finish_attempt(st, True, t0)
    assert ev == "confirmed" and st.confirmed_grade == "junior" and st.last_change_at is None
    # Middle ещё заблокирован ретраем
    assert not gp.check_attempt(st, "middle", t0 + timedelta(days=3)).allowed
    t1 = t0 + timedelta(days=15)
    assert gp.check_attempt(st, "middle", t1).allowed
    assert not gp.check_attempt(st, "senior", t1).allowed  # через ступень нельзя
    st = gp.start_attempt(st, "middle", t1)
    st, ev = gp.finish_attempt(st, True, t1)
    assert ev == "changed" and st.confirmed_grade == "middle" and st.last_change_at == t1
    # следующая смена — через 90 дней
    assert not gp.check_attempt(st, "senior", t1 + timedelta(days=30)).allowed
    assert gp.check_attempt(st, "senior", t1 + timedelta(days=91)).allowed
    # брошенная попытка = неудачная
    st = gp.start_attempt(st, "senior", t1 + timedelta(days=91))
    st, _ = gp.finish_attempt(st, None, t1 + timedelta(days=91))
    assert st.attempts[-1].status == "abandoned" and st.confirmed_grade == "middle"
    assert not gp.check_attempt(st, "senior", t1 + timedelta(days=95)).allowed


def test_cusum_flags_leaked_family_only():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.3, 0.7, 300)
    honest = [(float(pi), bool(rng.random() < pi)) for pi in p]
    leaked = [(float(pi), bool(rng.random() < (pi + (1 - pi) * 0.6))) for pi in p]
    assert run_cusum(honest).flagged_at is None
    assert run_cusum(leaked).flagged_at is not None


def test_calibration_recovers_difficulty():
    rng = np.random.default_rng(1)
    true = [ItemParams(1.2, b, 0.0) for b in np.linspace(-1.5, 1.5, 8)]
    prior = [ItemParams(1.3, t.b + rng.normal(0, 0.6), 0.0) for t in true]
    thetas = rng.normal(0, 1, 800)
    person, item, correct = [], [], []
    for i, th in enumerate(thetas):
        for j in rng.choice(len(true), 5, replace=False):
            person.append(i)
            item.append(int(j))
            correct.append(bool(rng.random() < prob(th, true[j].a, true[j].b)))
    est = calibrate(person, item, correct, prior)
    err_prior = np.mean([abs(p.b - t.b) for p, t in zip(prior, true)])
    err_est = np.mean([abs(e.b - t.b) for e, t in zip(est, true)])
    assert err_est < err_prior and err_est < 0.25
