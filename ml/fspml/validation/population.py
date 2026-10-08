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
from functools import lru_cache

import numpy as np
import yaml

from ..catalog import DATA_DIR, get_catalog
from ..matching.experience import effective_years, years_from, years_ru
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

# История работы (history=True). Генерируется отдельным потоком случайных чисел на кандидата,
# чтобы не сдвигать остальные скрытые признаки: замороженные бенчмарки строятся без истории.
JOB_TITLES = {
    "backend": ["Backend-разработчик", "Python-разработчик", "Java-разработчик", "Go-разработчик"],
    "frontend": ["Frontend-разработчик", "React-разработчик", "Верстальщик"],
    "data_science": ["Data Scientist", "ML-инженер", "Аналитик данных"],
    "qa": ["QA-инженер", "Тестировщик", "Инженер по автотестам"],
    "devops": ["DevOps-инженер", "SRE-инженер", "Системный администратор"],
    "analyst": ["Системный аналитик", "Бизнес-аналитик"],
    "mobile": ["Android-разработчик", "iOS-разработчик", "Flutter-разработчик"],
}
NON_IT_TITLES = ["Менеджер по продажам", "Инженер-конструктор", "Бухгалтер", "Преподаватель", "Логист"]
COMPANIES = ["Вектор", "Цифра", "Платформа", "Датасфера", "Север", "Код", "Горизонт", "Сфера", "Альфа-Тех"]
P_GRADUATE = {"intern": 0.7, "junior": 0.35}  # без коммерческого опыта
P_SWITCHER = 0.2  # пришёл из другой роли или профессии
# Требование вакансии к опыту по грейду (как пишут в объявлениях)
NEED_YEARS = {"junior": [0, 1, 1, 1], "middle": [2, 3, 3], "senior": [3, 4, 5, 5], "lead": [5, 6, 6]}

# Прежний общий состав теста специализации («$language» — язык по стеку, по умолчанию первый).
# Заморожен здесь: по нему сгенерированы навыки синтетической популяции и карточки размеченных
# бенчмарков; изменение порядка или набора навыков сдвинуло бы поток случайных чисел и сломало
# воспроизводимость скрытой истины. Продукт использует catalog.blueprint (ядро + модули стека).
LEGACY_BLUEPRINTS: dict[str, dict[str, float]] = {
    "backend": {
        "algorithms": 0.15,
        "sql": 0.2,
        "http": 0.15,
        "architecture": 0.1,
        "git": 0.05,
        "linux": 0.05,
        "docker": 0.05,
        "security": 0.05,
        "$language": 0.2,
    },
    "frontend": {
        "javascript": 0.3,
        "html_css": 0.15,
        "react": 0.15,
        "typescript": 0.1,
        "http": 0.15,
        "algorithms": 0.1,
        "git": 0.05,
    },
    "mobile": {"mobile": 0.4, "algorithms": 0.2, "http": 0.2, "git": 0.1, "architecture": 0.1},
    "data_science": {"python": 0.15, "pandas": 0.15, "statistics": 0.25, "ml": 0.3, "sql": 0.15},
    "qa": {"testing": 0.45, "http": 0.2, "sql": 0.15, "python": 0.1, "git": 0.1},
    "devops": {
        "linux": 0.25,
        "docker": 0.2,
        "kubernetes": 0.15,
        "cicd": 0.15,
        "http": 0.1,
        "git": 0.05,
        "security": 0.1,
    },
    "analyst": {"requirements": 0.35, "sql": 0.25, "http": 0.15, "metrics": 0.25},
}
LEGACY_STACK_LANGUAGES: dict[str, tuple[str, ...]] = {"backend": ("python", "javascript")}
# Технологии, по которым на момент заморозки популяции в банке не было заданий: они не попадали
# в пул «накрутки» стека. Пул заморожен так же, как состав теста выше, — иначе появление заданий
# по Java/Go/C#/PHP сдвинуло бы поток случайных чисел и сменило скрытую истину.
LEGACY_NO_TASKS = frozenset({"Java", "Go", "C#", "PHP"})


def legacy_blueprint(spec: str, stack: list[str] | None = None) -> dict[str, float]:
    """Прежний состав теста: общий для специализации, «$language» — первый язык стека или Python."""
    stack_l = {s.lower() for s in (stack or []) if s}
    langs = LEGACY_STACK_LANGUAGES.get(spec, ())
    bp: dict[str, float] = {}
    for skill, w in LEGACY_BLUEPRINTS[spec].items():
        if skill == "$language":
            lang = next((x for x in langs if x in stack_l), None) or (langs[0] if langs else None)
            if lang:
                bp[lang] = bp.get(lang, 0.0) + w
        else:
            bp[skill] = bp.get(skill, 0.0) + w
    total = sum(bp.values())
    return {k: v / total for k, v in bp.items()}


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
    # история работы (history=True); None — без истории (замороженные бенчмарки)
    relevant_years: float | None = None
    it_years: float | None = None
    industry_years: dict[str, float] = field(default_factory=dict)
    jobs: list[dict] = field(default_factory=list)


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
    min_years: float | None = None  # требуемый опыт (history=True)


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


@lru_cache(maxsize=1)
def _archetypes() -> dict[str, list[dict]]:
    raw = yaml.safe_load((DATA_DIR / "stack_archetypes.yaml").read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    for a in raw["archetypes"]:
        out.setdefault(a["spec"], []).append(a)
    return out


def _archetype_techs(
    rng: random.Random, spec: str, g_idx: int, *, need: bool = False
) -> tuple[str, set[str]]:
    """Реалистичный стек: архетип специализации (data/stack_archetypes.yaml) + вероятностный набор.

    core — почти всегда, common — часто, optional — иногда; с ростом грейда стек шире.
    """
    arch = _archetypes()[spec]
    a = rng.choices(arch, [x["share"] for x in arch])[0]
    p_core, p_common, p_opt = (0.95, 0.55, 0.25) if need else (0.9, 0.45 + 0.05 * g_idx, 0.12 + 0.05 * g_idx)
    techs = {t for t in a["core"] if rng.random() < p_core}
    techs |= {t for t in a["common"] if rng.random() < p_common}
    techs |= {t for t in a["optional"] if rng.random() < p_opt}
    if not techs:
        techs.add(a["core"][0])
    return a["id"], techs


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


def make_candidates(
    n: int = 1000,
    seed: int = 7,
    stuffing_rate: float = 0.3,
    *,
    realistic: bool = False,
    force_language: bool = True,
    history: bool = False,
) -> list[TrueCandidate]:
    """realistic=True — стек из архетипов (реальные связки технологий) вместо независимой выборки.

    force_language=False — backend-кандидат не получает Python/Node.js «в нагрузку» к архетипу:
    Java-, Go-, C#-разработчики знают только свой стек (для проверки состава теста). По умолчанию
    True — так построены популяции бенчмарков.

    history=True — история работы: выпускники без опыта, сменившие профессию, опыт по отраслям.
    """
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
        stack_languages = LEGACY_STACK_LANGUAGES.get(spec, ())
        if stack_languages:
            lang = rng.choice(stack_languages)
            stack = [lang]
        bp = legacy_blueprint(spec, stack)
        skill_theta = {s: theta + rng.gauss(0, 0.45) for s in bp}
        if realistic:
            _, techs = _archetype_techs(rng, spec, g_idx)
            if stack_languages:  # языковой навык теста — по реальному стеку
                lang = (
                    "python"
                    if "Python" in techs
                    else "javascript"
                    if techs & {"JavaScript", "TypeScript", "Node.js"}
                    else (lang if force_language else None)
                )
                bp = legacy_blueprint(spec, [lang])
                skill_theta = {s_: theta + rng.gauss(0, 0.45) for s_ in bp}
        else:
            techs = _sample_techs(rng, spec, rng.randint(4, 8) + g_idx)
        if force_language and lang == "python":
            techs.add("Python")
        elif force_language and lang == "javascript":
            techs.add("Node.js")
            techs.add("JavaScript")
        stuffed: set[str] = set()
        # Допущение о «накрутке»: чаще накручивают более слабые кандидаты, и накручивают то,
        # в чём они слабы (технологии из областей с наименьшей θ навыка). Поэтому тест способен
        # частично это вскрыть, а поиск по ключевым словам — нет.
        p_stuff = min(0.95, stuffing_rate * (1.5 if theta < 0.1 else 0.5))
        if rng.random() < p_stuff:
            dic = get_dictionary()
            pool = [
                t
                for t, _ in spec_techs(spec)
                if t not in techs and dic.techs[t].assess and t not in LEGACY_NO_TASKS
            ]

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
        if history:
            _add_history(c, random.Random(f"history-{seed}-{i}"))
        out.append(c)
    return out


def _add_history(c: TrueCandidate, rng: random.Random) -> None:
    """Места работы: релевантный опыт (та же специализация) и предыдущая карьера у части кандидатов."""
    cat = get_catalog()
    inds = [x["id"] for x in cat.industries if x["id"] != "other"]

    def industry() -> str:
        return rng.choice(sorted(c.industries)) if c.industries and rng.random() < 0.6 else rng.choice(inds)

    relevant, prior, prior_it = c.years, 0.0, False
    if rng.random() < P_GRADUATE.get(c.grade, 0.0):
        relevant = 0.0
    elif c.grade != "intern" and rng.random() < P_SWITCHER:
        relevant = round(c.years * rng.uniform(0.25, 0.6), 1)
        prior = round(rng.uniform(1.5, 6.0), 1)
        prior_it = rng.random() < 0.5
    jobs: list[dict] = []
    end_m = TODAY.year * 12 + TODAY.month - 1

    def add(title: str, spec: str | None, years: float, current: bool) -> None:
        nonlocal end_m
        months = max(1, round(years * 12))
        start_m = end_m - months + 1
        jobs.append(
            {
                "title": f"{title}, «{rng.choice(COMPANIES)}»",
                "start": f"{start_m // 12}-{start_m % 12 + 1:02d}",
                "end": None if current else f"{end_m // 12}-{end_m % 12 + 1:02d}",
                "specialization": spec,
                "industry": industry() if spec else None,
                "years": round(months / 12, 1),
            }
        )
        end_m = start_m - rng.randint(0, 3)  # перерыв между работами

    # релевантный опыт — 1–3 места, последнее — текущее
    left = relevant
    n_rel = 1 if relevant < 2 else rng.randint(1, min(3, int(relevant // 1.5) + 1))
    for k in range(n_rel):
        part = left if k == n_rel - 1 else round(left * rng.uniform(0.3, 0.7), 1)
        if part >= 0.1:
            add(rng.choice(JOB_TITLES[c.spec]), c.spec, part, current=k == 0)
        left -= part
    if prior > 0:
        if prior_it:
            other = rng.choice([s for s in JOB_TITLES if s != c.spec])
            add(rng.choice(JOB_TITLES[other]), other, prior, current=not jobs)
        else:
            add(rng.choice(NON_IT_TITLES), None, prior, current=not jobs)
    c.jobs = jobs
    c.relevant_years = round(sum(j["years"] for j in jobs if j["specialization"] == c.spec), 1)
    c.it_years = round(sum(j["years"] for j in jobs if j["specialization"]), 1)
    c.years = round(sum(j["years"] for j in jobs), 1)
    by_ind: dict[str, float] = {}
    for j in jobs:
        if j["industry"]:
            by_ind[j["industry"]] = round(by_ind.get(j["industry"], 0.0) + j["years"], 1)
    c.industry_years = by_ind
    head = c.resume_text.split(" Опыт ")[0]
    tail = c.resume_text.split(" Стек: ", 1)[1]
    exp = (
        "Опыт работы: " + "; ".join(f"{j['title']} — {years_ru(j['years'])}" for j in jobs) + "."
        if jobs
        else "Коммерческого опыта пока нет."
    )
    c.resume_text = f"{head} {exp} Стек: {tail}"


def make_needs(
    n: int = 30, seed: int = 11, *, realistic: bool = False, history: bool = False
) -> list[TrueNeed]:
    rng = random.Random(seed)
    cat = get_catalog()
    specs, shares = zip(*SPEC_SHARE.items())
    out = []
    for i in range(n):
        spec = rng.choices(specs, shares)[0]
        grade = rng.choices(["junior", "middle", "senior", "lead"], [0.25, 0.4, 0.28, 0.07])[0]
        if realistic:
            arch_id, techs = _archetype_techs(rng, spec, 0, need=True)
            core = set(next(a for a in _archetypes()[spec] if a["id"] == arch_id)["core"])
        else:
            techs, core = _sample_techs(rng, spec, rng.randint(4, 7)), set()
        skills = {}
        must = []
        for t in sorted(techs):  # порядок множества строк зависит от PYTHONHASHSEED
            imp = 1.0 if (t in core or rng.random() < 0.65) else 0.45
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
        min_years = None
        if history:
            min_years = float(random.Random(f"need-years-{seed}-{i}").choice(NEED_YEARS[grade]))
            req = f"Опыт работы {years_from(min_years)}." if min_years else "Можно без опыта."
            text = text.replace(" Обязательно:", f" {req} Обязательно:", 1)
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
                min_years=min_years,
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
    level = 3 if rel >= 0.62 else 2 if rel >= 0.45 else 1 if rel >= 0.28 else 0
    # Опыт (если у потребности есть требование, а у кандидата — история): нехватка релевантного
    # опыта снижает оценку работодателя, его отсутствие при требовании — до «слабо подходит».
    if need.min_years and c.relevant_years is not None:
        eff = effective_years(c.relevant_years, c.it_years or 0.0)
        if eff < 0.5 * need.min_years:
            level = min(level, 1)
        elif eff < need.min_years:
            level = max(0, level - 1)
    return level


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
