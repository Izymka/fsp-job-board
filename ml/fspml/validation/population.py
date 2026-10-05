"""Синтетическая популяция кандидатов и потребностей со *скрытой истиной*.

Истинные признаки (специализация, способность θ и навыки, реальный стек, ожидания) знает только
генератор. Система видит лишь *наблюдаемое*: ответы в тесте, заявленный стек (с «накруткой»),
текст резюме, привязанные достижения ФСП. Эталонная релевантность считается по истине, поэтому
не совпадает по построению с формулой ранжирования.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from ..catalog import get_catalog
from ..matching.scoring import FspAchievement
from ..nlp.skills import get_dictionary

TODAY = date(2026, 10, 5)

SPEC_SHARE = {
    "backend": 0.26,
    "frontend": 0.2,
    "data_science": 0.14,
    "qa": 0.12,
    "devops": 0.1,
    "analyst": 0.1,
    "mobile": 0.08,
}
BASE_SALARY = {"intern": 60_000, "junior": 110_000, "middle": 210_000, "senior": 330_000, "lead": 420_000}
SPEC_SALARY = {
    "backend": 1.05,
    "frontend": 1.0,
    "data_science": 1.08,
    "qa": 0.82,
    "devops": 1.1,
    "analyst": 0.92,
    "mobile": 1.02,
}
YEARS_BY_GRADE = {"intern": (0, 0.5), "junior": (0.5, 2), "middle": (2, 4), "senior": (4, 7), "lead": (6, 12)}


@dataclass
class TrueCandidate:
    id: str
    spec: str
    theta: float
    grade: str
    skill_theta: dict[str, float]
    techs: set[str]  # реально владеет
    claimed: set[str]  # указал в профиле (реальные + накрутка)
    stuffed: set[str]
    claimed_grade: str
    fsp: list[FspAchievement] | None
    salary_from: int
    salary_to: int
    work_formats: set[str]
    industries: set[str]
    search_status: str
    last_active: date
    years: float
    practical: float = 0.0  # практический навык (то, что подтверждают соревнования ФСП)
    resume_text: str = ""
    lang: str | None = None


@dataclass
class TrueNeed:
    id: str
    spec: str
    grade: str
    skills: dict[str, float]
    salary_from: int
    salary_to: int
    work_format: str
    industry: str
    text: str = ""
    must: list[str] = field(default_factory=list)


def spec_techs(spec: str) -> list[tuple[str, float]]:
    dic = get_dictionary()
    return sorted(
        ((t.name, t.spec[spec]) for t in dic.techs.values() if t.spec.get(spec, 0) >= 0.4),
        key=lambda x: -x[1],
    )


def _sample_techs(rng: random.Random, spec: str, k: int) -> set[str]:
    pool = spec_techs(spec)
    names = [n for n, _ in pool]
    weights = [w for _, w in pool]
    out: set[str] = set()
    while len(out) < min(k, len(names)):
        out.add(rng.choices(names, weights)[0])
    return out


def _fsp_history(rng: random.Random, practical: float, spec: str) -> list[FspAchievement] | None:
    cat = get_catalog()
    if rng.random() > 0.4:  # у ~60% истории ФСП нет
        return None
    n = rng.choice([0, 1, 1, 2, 2, 3, 4])
    disciplines = [d["id"] for d in cat.fsp["disciplines"]]
    rel = [cat.fsp_relevance(d, spec) for d in disciplines]
    out = []
    for _ in range(n):
        strength = practical + rng.gauss(0, 0.5)
        result = (
            "winner"
            if strength > 1.8
            else "prize"
            if strength > 1.0
            else "finalist"
            if strength > 0.2
            else "participant"
        )
        level = rng.choices(["international", "national", "regional", "local"], [0.05, 0.35, 0.45, 0.15])[0]
        out.append(
            FspAchievement(
                discipline=rng.choices(disciplines, rel)[0],
                level=level,
                result=result,
                event_date=TODAY - timedelta(days=rng.randint(30, 365 * 5)),
            )
        )
    return out


ABOUT = {
    "backend": [
        "Разрабатываю серверную часть и API",
        "Проектирую сервисы и базы данных",
        "Занимаюсь интеграциями и производительностью",
    ],
    "frontend": [
        "Делаю интерфейсы веб-приложений",
        "Верстаю и пишу клиентскую логику",
        "Слежу за производительностью и доступностью UI",
    ],
    "data_science": [
        "Строю модели машинного обучения",
        "Анализирую данные и провожу эксперименты",
        "Готовлю признаки и оцениваю модели",
    ],
    "qa": ["Тестирую веб и API", "Пишу тест-кейсы и автотесты", "Нахожу и описываю дефекты"],
    "devops": [
        "Поддерживаю инфраструктуру и CI/CD",
        "Настраиваю кластеры и мониторинг",
        "Автоматизирую развёртывание",
    ],
    "analyst": [
        "Собираю и формализую требования",
        "Моделирую процессы и интеграции",
        "Считаю продуктовые метрики",
    ],
    "mobile": [
        "Разрабатываю мобильные приложения",
        "Делаю экраны и офлайн-режим",
        "Публикую приложения в сторах",
    ],
}


def make_candidates(n: int = 1000, seed: int = 7, stuffing_rate: float = 0.3) -> list[TrueCandidate]:
    rng = random.Random(seed)
    cat = get_catalog()
    specs, shares = zip(*SPEC_SHARE.items())
    out = []
    for i in range(n):
        spec = rng.choices(specs, shares)[0]
        theta = rng.gauss(0.1, 1.0)
        grade = cat.grade_for_theta(theta).id
        g_idx = cat.grade_index(grade)
        # самооценка грейда: чаще верная, иногда завышенная
        r = rng.random()
        claim_idx = g_idx + (1 if r < 0.25 else -1 if r < 0.37 else 0)
        claim_idx = max(0, min(len(cat.grades) - 1, claim_idx))
        lang = None
        stack = None
        spec_obj = cat.specializations[spec]
        if spec_obj.stack_languages:
            lang = rng.choice(spec_obj.stack_languages)
            stack = [lang]
        bp = cat.blueprint(spec, stack)
        skill_theta = {s: theta + rng.gauss(0, 0.45) for s in bp}
        techs = _sample_techs(rng, spec, rng.randint(4, 8) + g_idx)
        if lang == "python":
            techs.add("Python")
        elif lang == "javascript":
            techs.add("Node.js")
            techs.add("JavaScript")
        stuffed: set[str] = set()
        # Допущение о «накрутке»: чаще накручивают более слабые кандидаты, и накручивают то,
        # в чём они слабы (технологии из областей с наименьшей θ навыка). Поэтому тест способен
        # частично это вскрыть, а поиск по ключевым словам — нет.
        p_stuff = min(0.95, stuffing_rate * (1.5 if theta < 0.1 else 0.5))
        if rng.random() < p_stuff:
            dic = get_dictionary()
            pool = [t for t, _ in spec_techs(spec) if t not in techs and dic.techs[t].assess]

            def weakness(t, dic=dic, skill_theta=skill_theta, theta=theta):
                vals = [skill_theta[a] for a in dic.techs[t].assess if a in skill_theta]
                return (sum(vals) / len(vals)) if vals else theta + 1.0

            pool.sort(key=lambda t: weakness(t) + rng.gauss(0, 0.2))
            stuffed = set(pool[: rng.randint(3, 6)])
            real_cover = {a for t in techs for a in dic.techs[t].assess}
            for t in stuffed:
                for a in dic.techs[t].assess:
                    if a in skill_theta and a not in real_cover:
                        skill_theta[a] -= 0.5
                        real_cover.add(a)
        practical = theta + rng.gauss(0, 0.6)
        sal = BASE_SALARY[grade] * SPEC_SALARY[spec] * rng.lognormvariate(0, 0.15)
        sal_from = int(round(sal / 10_000) * 10_000)
        years = rng.uniform(*YEARS_BY_GRADE[grade])
        status = rng.choices(["active", "open", "closed"], [0.5, 0.4, 0.1])[0]
        c = TrueCandidate(
            id=f"c{i:04d}",
            spec=spec,
            theta=theta,
            grade=grade,
            skill_theta=skill_theta,
            techs=techs,
            claimed=techs | stuffed,
            stuffed=stuffed,
            claimed_grade=cat.grades[claim_idx].id,
            fsp=_fsp_history(rng, practical, spec),
            salary_from=sal_from,
            salary_to=int(sal_from * rng.uniform(1.1, 1.3)),
            work_formats=set(rng.sample(["office", "hybrid", "remote"], rng.randint(1, 3))),
            industries=set(rng.sample([x["id"] for x in cat.industries], rng.randint(0, 2))),
            search_status=status,
            last_active=TODAY - timedelta(days=int(rng.expovariate(1 / 20))),
            years=years,
            practical=practical,
            lang=lang,
        )
        claimed_title = cat.grades[claim_idx].name
        c.resume_text = (
            f"{cat.specializations[spec].title} {claimed_title}. {rng.choice(ABOUT[spec])}. "
            f"Опыт {years:.1f} лет. Стек: {', '.join(sorted(c.claimed))}. "
            + " ".join(f"Работал с {t}." for t in rng.sample(sorted(c.claimed), min(3, len(c.claimed))))
        )
        out.append(c)
    return out


def make_needs(n: int = 30, seed: int = 11) -> list[TrueNeed]:
    rng = random.Random(seed)
    cat = get_catalog()
    specs, shares = zip(*SPEC_SHARE.items())
    out = []
    for i in range(n):
        spec = rng.choices(specs, shares)[0]
        grade = rng.choices(["junior", "middle", "senior", "lead"], [0.25, 0.4, 0.28, 0.07])[0]
        techs = _sample_techs(rng, spec, rng.randint(4, 7))
        skills = {}
        must = []
        for t in techs:
            imp = 1.0 if rng.random() < 0.65 else 0.45
            skills[t] = imp
            if imp >= 0.6:
                must.append(t)
        base = BASE_SALARY[grade] * SPEC_SALARY[spec]
        sal_from = int(round(base * rng.uniform(0.85, 1.05) / 10_000) * 10_000)
        sal_to = int(round(sal_from * rng.uniform(1.15, 1.35) / 10_000) * 10_000)
        fmt = rng.choice(["office", "hybrid", "remote"])
        industry = rng.choice([x["id"] for x in cat.industries])
        text = (
            f"Ищем {cat.specializations[spec].title.lower()} уровня {cat.grade(grade).name}. "
            f"{rng.choice(ABOUT[spec])}. Обязательно: {', '.join(must) or ', '.join(techs)}. "
            f"Будет плюсом: {', '.join(t for t in techs if t not in must) or 'опыт в отрасли'}. "
            f"Вилка {sal_from}–{sal_to} ₽, формат: {fmt}."
        )
        out.append(
            TrueNeed(
                id=f"n{i:02d}",
                spec=spec,
                grade=grade,
                skills=skills,
                salary_from=sal_from,
                salary_to=sal_to,
                work_format=fmt,
                industry=industry,
                text=text,
                must=must,
            )
        )
    return out


def true_relevance(c: TrueCandidate, need: TrueNeed) -> int:
    """Градуированная эталонная релевантность 0–3 по скрытым признакам.

    Учитывает: истинную специализацию и грейд, реальное владение требуемыми технологиями
    (не заявленное!), истинную силу в навыках относительно порога грейда, готовность к
    предложению (статус поиска, вилка, формат).
    """
    cat = get_catalog()
    dic = get_dictionary()
    if c.spec != need.spec or c.search_status == "closed":
        return 0
    gdiff = abs(cat.grade_index(c.grade) - cat.grade_index(need.grade))
    if gdiff >= 2:
        return 0
    grade_match = 1.0 if gdiff == 0 else 0.55
    tot = sum(need.skills.values())
    know = sum(w for t, w in need.skills.items() if t in c.techs) / tot
    # сила в навыках, которые требует вакансия, относительно порога её грейда
    cut = cat.grade(need.grade).cut
    req_assess = {a for t in need.skills for a in dic.techs[t].assess}
    vals = [c.skill_theta[a] for a in req_assess if a in c.skill_theta] or [c.theta]
    # Допущение: реальная результативность = знания (то, что меряет тест) + практика (то, что
    # видно по соревнованиям); практика — независимая от теста компонента.
    ability = 0.7 * float(np.mean(vals)) + 0.3 * c.practical
    strength = float(np.clip((ability - cut + 1.0) / 2.0, 0, 1))
    salary_ok = c.salary_from <= need.salary_to * 1.05
    format_ok = need.work_format in c.work_formats or "hybrid" in (need.work_format, *c.work_formats)
    cond = 1.0 if (salary_ok and format_ok) else 0.6 if (salary_ok or format_ok) else 0.35
    rel = grade_match * (0.55 * know + 0.45 * strength) * cond
    return 3 if rel >= 0.62 else 2 if rel >= 0.45 else 1 if rel >= 0.28 else 0


def accept_probability(c: TrueCandidate, need: TrueNeed) -> float:
    """Модель решения кандидата по приглашению (для метрики «ожидаемые принятые приглашения»)."""
    if c.search_status == "closed":
        return 0.02
    p = 0.75 if c.search_status == "active" else 0.45
    if need.salary_to < c.salary_from:
        p *= max(0.05, 1 - 3 * (c.salary_from - need.salary_to) / c.salary_from)
    if need.work_format not in c.work_formats and need.work_format != "hybrid":
        p *= 0.4
    if c.spec != need.spec:
        p *= 0.2
    return p
