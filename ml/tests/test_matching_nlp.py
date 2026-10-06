from __future__ import annotations

from dataclasses import replace
from datetime import date

import yaml
from fspml.catalog import DATA_DIR
from fspml.matching.scoring import (
    CandidateFeatures,
    FspAchievement,
    Need,
    fsp_strength,
    rank,
    rank_in_category,
    recommend_categories,
    salary_fit,
)
from fspml.nlp.resume import parse_resume_text
from fspml.nlp.skills import get_dictionary
from fspml.nlp.vacancy import parse_need

TODAY = date(2026, 10, 5)


def cand(cid: str, **kw) -> CandidateFeatures:
    base = dict(
        id=cid,
        specialization="backend",
        grade="middle",
        theta=0.3,
        theta_se=0.35,
        skill_status={"python": "confirmed", "sql": "confirmed", "http": "uncertain"},
        claimed={"Python", "PostgreSQL", "FastAPI", "Docker"},
        salary_from=250_000,
        salary_to=300_000,
        work_formats={"remote", "hybrid"},
        search_status="active",
        last_active=TODAY,
        tested_at=TODAY,
    )
    base.update(kw)
    return CandidateFeatures(**base)


NEED = Need(
    specialization="backend",
    grade="middle",
    skills={"Python": 1.0, "PostgreSQL": 1.0, "FastAPI": 0.8, "Kubernetes": 0.45},
    salary_from=240_000,
    salary_to=320_000,
    work_format="remote",
)


def test_confirmed_beats_claimed_and_visibility_rules():
    strong = cand("strong")
    claims = cand("claims", skill_status={}, theta=0.3)
    weak = cand("weak", skill_status={"python": "weak", "sql": "weak"})
    closed = cand("closed", search_status="closed")
    other_spec = cand("front", specialization="frontend")
    senior = cand("senior", grade="senior", theta=1.2)
    lead = cand("lead", grade="lead", theta=2.0)
    res = rank([weak, claims, strong, closed, other_spec, senior, lead], NEED, TODAY)
    ids = [r.candidate_id for r in res]
    assert "closed" not in ids and "front" not in ids and "lead" not in ids
    assert ids.index("strong") < ids.index("claims") < ids.index("weak")
    sen = next(r for r in res if r.candidate_id == "senior")
    assert sen.adjacent and any("Соседняя категория" in x.text for x in sen.reasons)
    top = res[0]
    assert sum(top.components.values()) == top.score or abs(sum(top.components.values()) - top.score) < 1e-3
    assert any("Подтверждено тестом" in r.text for r in top.reasons)


def test_excluded_industry_and_company():
    c = cand("x", excluded_industries={"fintech"}, excluded_companies={"acme"})
    assert not rank([c], replace(NEED, industry="fintech"), TODAY)
    assert not rank([c], replace(NEED, company_id="acme"), TODAY)
    assert rank([c], NEED, TODAY)


def test_no_fsp_history_is_neutral_and_fsp_saturates():
    no_fsp = cand("nofsp", fsp=None)
    with_fsp = cand("fsp", fsp=[FspAchievement("product", "national", "winner", date(2026, 3, 1))])
    res = {r.candidate_id: r for r in rank([no_fsp, with_fsp], NEED, TODAY)}
    assert any("не привязан" in x.text and x.kind == "neutral" for x in res["nofsp"].reasons)
    assert res["fsp"].profile_strength > res["nofsp"].profile_strength
    many = [FspAchievement("product", "local", "participant", date(2025, 1, 1))] * 10
    assert fsp_strength(many, "backend", TODAY) < 1.0
    assert fsp_strength(None, "backend", TODAY) == 0.0
    order_ = rank_in_category([no_fsp, with_fsp], "backend", "middle", TODAY)
    assert order_[0][0] == "fsp"


def test_salary_fit_categories():
    c = cand("s", salary_from=250_000, salary_to=300_000)
    assert salary_fit(c, 260_000, 320_000)[1] == "within"
    assert salary_fit(c, 200_000, 260_000)[1] == "partial"
    assert salary_fit(c, 150_000, 200_000)[1] == "below"
    assert salary_fit(replace(c, salary_from=None), 1, 2)[1] == "unknown"


def test_recommend_categories():
    pool = [cand(f"m{i}") for i in range(5)] + [
        cand(f"s{i}", grade="senior", salary_from=400_000) for i in range(3)
    ]
    cats = recommend_categories(pool, NEED)
    target = next(c for c in cats if c.relation == "target")
    assert target.total == 5 and target.in_budget_share == 1.0
    assert any(c.grade == "senior" and c.total == 3 for c in cats)


def test_skill_extraction_aliases_and_typos():
    dic = get_dictionary()
    found = dic.extract("Опыт с Postgress, k8s, питон, React.js и C++; язык Go; резюме CV")
    assert {"PostgreSQL", "Kubernetes", "Python", "React", "C++", "Go"} <= set(found)
    assert "Computer vision" not in found


def test_demo_vacancies_parse_correctly():
    vs = yaml.safe_load((DATA_DIR / "vacancies.yaml").read_text(encoding="utf-8"))["vacancies"]
    for v in vs:
        n = parse_need(v["text"], v["title"])
        assert n.specialization == v["expected"]["specialization"], v["id"]
        assert n.grade == v["expected"]["grade"], v["id"]
        assert n.salary_from and n.salary_to and n.salary_from < n.salary_to
        assert abs(sum(n.blueprint.values()) - 1) < 0.01


def test_resume_text_parsing():
    r = parse_resume_text(
        "Петров Иван Олегович\nFrontend-разработчик\nКазань · ivan@example.ru · +7 900 111-22-33\n\n"
        "Опыт работы\nООО «Веб» — Middle Frontend Developer\n01.2021 — по настоящее время\nReact, TypeScript, Redux\n\n"
        "Навыки\nJavaScript, HTML, CSS, Git"
    )
    assert r.full_name == "Петров Иван Олегович"
    assert r.email == "ivan@example.ru" and r.phone == "+79001112233" and r.city == "Казань"
    assert {"React", "TypeScript", "JavaScript"} <= set(r.skills)
    assert r.experience_years >= 5 and r.specialization_hint == "frontend"


def test_need_inline_headings_and_salary_formats():
    text = (
        "Ищем бэкенд-разработчика в команду платёжного шлюза.\n"
        "Задачи: микросервисы на Python (FastAPI), оптимизация PostgreSQL.\n"
        "Обязательно: Python, PostgreSQL, Docker, опыт от 2 лет.\n"
        "Будет плюсом: Kubernetes, gRPC.\n"
        "Вилка 250–320 тыс. ₽, гибрид в Москве."
    )
    n = parse_need(text)
    assert {"Kubernetes", "gRPC"} <= set(n.plus)
    assert "Python" in n.must and n.skills["Python"] > n.skills["Kubernetes"]
    assert (n.salary_from, n.salary_to) == (250_000, 320_000)
    assert n.work_format == "hybrid" and n.grade == "middle"
    for t, exp in [
        ("от 300 000 до 400 000 руб", (300_000, 400_000)),
        ("200-260k ₽", (200_000, 260_000)),
        ("ЗП 180 000 ₽", (180_000, None)),
    ]:
        assert parse_need("Python-разработчик. " + t).salary_from == exp[0], t


def test_resume_hh_layout_pdf():
    """Выгрузка hh.ru: даты в левой колонке и разнесены на две строки — опыт должен находиться."""
    import random

    from fspml.nlp.resume import parse_resume_pdf
    from fspml.validation.resume import make_hh_resume

    rng = random.Random(5)
    for _ in range(8):
        truth, pdf = make_hh_resume(rng)
        r = parse_resume_pdf(pdf)
        assert r.layout == "hh"
        assert len(r.jobs) == truth.n_jobs
        assert all(j.position and j.company for j in r.jobs)
        assert abs(r.experience_years - truth.years) <= 0.1
        assert abs(r.it_experience_years - truth.it_years) <= 0.1
        assert r.headline and r.email == truth.email


def test_resume_text_two_line_period_and_non_it_experience():
    r = parse_resume_text(
        "Сидорова Анна\nanna@example.ru\n"
        "Опыт работы — 6 лет 2 месяца\n"
        "Сентябрь 2023 — ООО «Код»\nнастоящее время\n3 года 1 месяц\nPython-разработчик\n"
        "FastAPI, PostgreSQL, Docker, Kafka\n"
        "Август 2020 — ГБОУ Школа №1\nАвгуст 2023\n3 года 1 месяц\nУчитель\n"
        "Разрабатывала и проводила уроки математики\n"
        "Образование\nВысшее"
    )
    assert len(r.jobs) == 2 and r.jobs[0].title == "ООО «Код»"
    assert [j.it for j in r.jobs] == [True, False]
    assert r.experience_years > r.it_experience_years >= 3
    assert r.grade_hint == "middle" and "всего" in r.grade_reason
