"""Демо-данные: python -m app.seed [--reset] [--candidates N]

* ~300 синтетических кандидатов, прошедших *симулированный* адаптивный тест (категории и
  подоценки получены тем же движком, что и у живых пользователей);
* компании из демонстрационных вакансий (ml/fspml/data/vacancies.yaml) с опубликованными вакансиями;
* регулярные задания, история приглашений с причинами отказов (для аналитики работодателя);
* демо-аккаунты: employer@demo.fsp (компания «Рубль+»), maria@demo.fsp (готовый кандидат
  Backend · Middle с привязанным ФСП ID), candidate@demo.fsp (пустой — для живого онбординга).
  Пароли задаются в Keycloak (keycloak/realm-fsp-jobs.json), здесь — только профили.
"""

from __future__ import annotations

import argparse
import random
from datetime import timedelta

import yaml
from fspml.catalog import DATA_DIR, get_catalog
from fspml.nlp.vacancy import parse_need
from fspml.validation.assessment import make_true_bank, simulate_onboarding
from fspml.validation.population import TODAY as POP_TODAY
from fspml.validation.population import make_candidates
from sqlalchemy import select

from .core.db import Base, SessionLocal, engine, utcnow
from .models import (
    CandidateProfile,
    Company,
    Consent,
    Invitation,
    RegularTask,
    User,
    Vacancy,
)
from .modules.fsp.client import RegistryUnavailable, fetch_participant, normalize_achievements

FIRST_M = [
    "Алексей",
    "Иван",
    "Дмитрий",
    "Сергей",
    "Никита",
    "Артём",
    "Кирилл",
    "Максим",
    "Егор",
    "Павел",
    "Роман",
    "Тимур",
]
FIRST_F = [
    "Мария",
    "Анна",
    "Екатерина",
    "Ольга",
    "Полина",
    "Дарья",
    "Софья",
    "Алина",
    "Виктория",
    "Ксения",
    "Елена",
    "Юлия",
]
LAST = [
    "Смирнов",
    "Кузнецов",
    "Попов",
    "Васильев",
    "Петров",
    "Соколов",
    "Михайлов",
    "Новиков",
    "Фёдоров",
    "Морозов",
    "Волков",
    "Алексеев",
    "Лебедев",
    "Семёнов",
    "Егоров",
    "Павлов",
]
PATR_M = ["Андреевич", "Сергеевич", "Игоревич", "Олегович", "Дмитриевич", "Алексеевич"]
PATR_F = ["Андреевна", "Сергеевна", "Игоревна", "Олеговна", "Дмитриевна", "Алексеевна"]
CITIES = [
    "Москва",
    "Санкт-Петербург",
    "Казань",
    "Новосибирск",
    "Екатеринбург",
    "Томск",
    "Самара",
    "Нижний Новгород",
    "Пермь",
    "Краснодар",
]
HEADLINES = {
    "backend": ["Backend-разработчик", "Python-разработчик", "Разработчик серверной части"],
    "frontend": ["Frontend-разработчик", "React-разработчик", "Веб-разработчик интерфейсов"],
    "data_science": ["Data Scientist", "ML-инженер", "Аналитик данных / ML"],
    "qa": ["QA-инженер", "Тестировщик", "Инженер по автотестам"],
    "devops": ["DevOps-инженер", "SRE-инженер", "Инженер инфраструктуры"],
    "analyst": ["Системный аналитик", "Бизнес-аналитик", "Аналитик требований"],
    "mobile": ["Android-разработчик", "iOS-разработчик", "Мобильный разработчик"],
}


def _name(rng: random.Random) -> str:
    female = rng.random() < 0.4
    last = rng.choice(LAST) + ("а" if female else "")
    return f"{last} {rng.choice(FIRST_F if female else FIRST_M)} {rng.choice(PATR_F if female else PATR_M)}"


def _translit(s: str) -> str:
    table = str.maketrans("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "abvgdeezziiklmnoprstufhccss_y_eua")
    return s.lower().translate(table).replace("_", "")


def reset() -> None:
    import app.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _consents(db, user: User) -> None:
    for kind in ("pd_processing", "profile_publication"):
        db.add(Consent(user_id=user.id, kind=kind, version="2026-10-01"))


def _fsp_for(fsp_id: str, fallback, offline: bool = False) -> tuple[list[dict], dict | None, bool]:
    try:
        if offline:
            raise RegistryUnavailable("offline")
        data = fetch_participant(fsp_id)
        return (
            normalize_achievements(data),
            ({k: data.get(k) for k in ("full_name", "region", "sport_rank")} if data else None),
            True,
        )
    except RegistryUnavailable:
        cat = get_catalog()
        lvl = {x["id"]: x["title"] for x in cat.fsp["levels"]}
        disc = {x["id"]: x["title"] for x in cat.fsp["disciplines"]}
        ach = [
            {
                "id": f"{fsp_id}-L{i}",
                "title": f"{lvl[a.level]} соревнования: {disc[a.discipline].lower()}",
                "discipline": a.discipline,
                "level": a.level,
                "result": a.result,
                "place": None,
                "date": a.event_date.isoformat(),
                "role": None,
                "team": None,
            }
            for i, a in enumerate(fallback or [])
        ]
        return ach, None, False


def seed(n_candidates: int = 300) -> None:
    rng = random.Random(42)
    with SessionLocal() as db:
        if db.scalar(select(Company.id).limit(1)):
            print("Данные уже есть — пропускаю (используйте --reset для пересоздания)")
            return
        now = utcnow()
        # ---------------------------------------------------------------- кандидаты
        pop = make_candidates(n_candidates, seed=2026, stuffing_rate=0.2, history=True)
        truth = make_true_bank()
        sim_rng = random.Random(7)
        registry_ok = True
        profiles: list[CandidateProfile] = []
        fsp_counter = 0
        for c in pop:
            ob = simulate_onboarding(c, truth, sim_rng)
            res = next((l.result for l in reversed(ob.logs) if l.result.decision == "confirmed"), None)
            name = _name(rng)
            u = User(
                email=f"{_translit(name.split()[1])}.{_translit(name.split()[0])}{rng.randint(1, 99)}@example.ru",
                email_verified=True,
                role="candidate",
                display_name=name,
                is_demo=True,
            )
            db.add(u)
            db.flush()
            _consents(db, u)
            fsp_id = ach = fsp_profile = None
            if c.fsp is not None:
                fsp_counter += 1
                fsp_id = f"FSP-{fsp_counter:06d}" if fsp_counter != 123 else "FSP-000401"
                # если реестр недоступен — не ждём таймаута на каждом кандидате
                ach, fsp_profile, ok = _fsp_for(fsp_id, c.fsp, offline=not registry_ok)
                registry_ok = registry_ok and ok
            years = round(c.years, 1)
            p = CandidateProfile(
                user_id=u.id,
                full_name=name,
                contact_email=u.email,
                phone=f"+79{rng.randint(100000000, 999999999)}",
                telegram="@" + _translit(name.split()[1])[:6] + str(rng.randint(10, 999)),
                city=rng.choice(CITIES),
                headline=rng.choice(HEADLINES[c.spec]),
                about=c.resume_text,
                experience_years=years,
                soft_skills=rng.sample(
                    [
                        "Коммуникация",
                        "Работа в команде",
                        "Самостоятельность",
                        "Менторство",
                        "Аналитическое мышление",
                        "Английский язык",
                    ],
                    2,
                ),
                experience=[
                    {
                        "title": j["title"],
                        "start": j["start"],
                        "end": j["end"],
                        "description": ("Стек: " + ", ".join(sorted(c.claimed)[:6]))
                        if j["specialization"] == c.spec
                        else None,
                        "specialization": j["specialization"],
                        "industry": j["industry"],
                    }
                    for j in c.jobs
                ],
                survey_completed_at=now - timedelta(days=rng.randint(1, 120)),
                industries=sorted(c.industries),
                specialization=c.spec,
                stack=sorted(c.claimed),
                work_formats=sorted(c.work_formats),
                salary_from=c.salary_from,
                salary_to=c.salary_to,
                search_status=c.search_status,
                claimed_grade=c.claimed_grade,
                confirmed_grade=ob.grade,
                confirmed_at=(now - timedelta(days=rng.randint(1, 90))) if ob.grade else None,
                theta=res.theta if res else None,
                theta_se=res.se if res else None,
                skill_scores={
                    k: {
                        "status": s.status,
                        "theta": s.theta,
                        "se": s.se,
                        "n": s.n_items,
                        "n_correct": s.n_correct,
                    }
                    for k, s in (res.skills.items() if res else [])
                },
                fsp_id=fsp_id,
                fsp_linked_at=now - timedelta(days=30) if fsp_id else None,
                fsp_synced_at=now if fsp_id else None,
                fsp_achievements=ach or [],
                fsp_profile=fsp_profile,
                last_active_at=now - timedelta(days=(POP_TODAY - c.last_active).days),
                tasks_score=round(rng.random() * 0.5, 2) if rng.random() < 0.25 else 0.0,
            )
            db.add(p)
            profiles.append(p)
        db.flush()

        # ---------------------------------------------------------------- компании и вакансии
        vac_data = yaml.safe_load((DATA_DIR / "vacancies.yaml").read_text(encoding="utf-8"))["vacancies"]
        companies: list[Company] = []
        for i, v in enumerate(vac_data):
            email = "employer@demo.fsp" if i == 0 else f"hr{i}@demo.fsp"
            u = User(
                email=email,
                email_verified=True,
                role="employer",
                display_name=f"HR {v['company']}",
                is_demo=True,
            )
            db.add(u)
            db.flush()
            db.add(Consent(user_id=u.id, kind="pd_processing", version="2026-10-01"))
            comp = Company(
                owner_id=u.id,
                name=v["company"],
                industry=v["industry"],
                description=v["text"].split("\n")[0],
                city=rng.choice(CITIES),
                contact_email=email,
            )
            db.add(comp)
            db.flush()
            companies.append(comp)
            n = parse_need(v["text"], v["title"])
            db.add(
                Vacancy(
                    company_id=comp.id,
                    title=v["title"],
                    text=v["text"],
                    specialization=v["expected"]["specialization"],
                    grade=v["expected"]["grade"],
                    skills=n.skills,
                    salary_from=n.salary_from or 150000,
                    salary_to=n.salary_to or 250000,
                    work_format=n.work_format,
                    min_years=n.min_years,
                    city=comp.city,
                    status="published",
                    blueprint=n.blueprint,
                    parsed={"must": n.must, "plus": n.plus, "explanation": n.explanation},
                )
            )
        db.flush()

        # ---------------------------------------------------------------- регулярные задания
        tasks = [
            (0, "SQL-разминка по платёжным данным", "auto", "backend", "sql", None),
            (
                0,
                "Как бы вы спроектировали идемпотентный API платежей?",
                "open",
                "backend",
                None,
                "Опишите подход к повторной отправке платежа при сетевых сбоях: ключи идемпотентности, хранение, ответы клиенту.",
            ),
            (1, "JavaScript: event loop", "auto", "frontend", "javascript", None),
            (2, "Статистика для A/B-тестов", "auto", "data_science", "statistics", None),
            (3, "Тест-дизайн формы заявления", "auto", "qa", "testing", None),
            (4, "Kubernetes: rolling update", "auto", "devops", "kubernetes", None),
            (5, "Продуктовые метрики кредитного конвейера", "auto", "analyst", "metrics", None),
        ]
        for ci, title, kind, spec, skill, prompt in tasks:
            db.add(
                RegularTask(
                    company_id=companies[ci].id,
                    title=title,
                    kind=kind,
                    specialization=spec,
                    skill=skill,
                    prompt=prompt,
                    rubric="Корректность, учёт крайних случаев, ясность изложения"
                    if kind == "open"
                    else None,
                )
            )

        # ---------------------------------------------------------------- история приглашений
        reasons = ["salary", "salary", "salary", "stack", "format", "company", "not_looking"]
        visible = [p for p in profiles if p.confirmed_grade and p.search_status != "closed"]
        for ci, comp in enumerate(companies):
            # у демо-компании («Рубль+») — история только с завершёнными ответами, чтобы аналитика
            # отказов была видна сразу, а новые приглашения на демо отправлялись «с нуля»
            spec_pool = [
                p for p in visible if p.specialization == vac_data[ci]["expected"]["specialization"]
            ] or visible
            pool = rng.sample(spec_pool, min(8, len(spec_pool)))
            for p in pool:
                weights = [0.4, 0.6, 0.0, 0.0] if ci == 0 else [0.35, 0.4, 0.15, 0.1]
                status = rng.choices(["accepted", "declined", "viewed", "sent"], weights)[0]
                created = now - timedelta(days=rng.randint(1, 60))
                inv = Invitation(
                    company_id=comp.id,
                    candidate_id=p.user_id,
                    title=rng.choice(HEADLINES.get(p.specialization, ["Специалист"])),
                    description="Приглашаем обсудить позицию в нашей команде.",
                    salary_from=int((p.salary_from or 150000) * rng.uniform(0.75, 1.0) // 10000 * 10000),
                    salary_to=int((p.salary_from or 150000) * rng.uniform(1.0, 1.3) // 10000 * 10000),
                    contact_method="email",
                    contact_value=comp.contact_email or "hr@example.ru",
                    status=status,
                    decline_reason=rng.choice(reasons) if status == "declined" else None,
                    created_at=created,
                    viewed_at=created + timedelta(hours=rng.randint(1, 48)) if status != "sent" else None,
                    responded_at=created + timedelta(hours=rng.randint(2, 96))
                    if status in ("accepted", "declined")
                    else None,
                )
                db.add(inv)

        # ---------------------------------------------------------------- демо-кандидат «Мария»
        u = User(
            email="maria@demo.fsp",
            email_verified=True,
            role="candidate",
            display_name="Иванова Мария Сергеевна",
            is_demo=True,
        )
        db.add(u)
        db.flush()
        _consents(db, u)
        ach, fsp_profile, _ = _fsp_for("FSP-000123", [])
        demo_src = next(
            p for p in profiles if p.specialization == "backend" and p.confirmed_grade == "middle"
        )
        db.add(
            CandidateProfile(
                user_id=u.id,
                full_name="Иванова Мария Сергеевна",
                contact_email="maria@demo.fsp",
                phone="+79161234567",
                telegram="@mivanova_dev",
                github="mivanova",
                city="Москва",
                headline="Python-разработчик",
                about="Бэкенд-разработчик: платёжные сервисы на FastAPI, PostgreSQL, Kafka. Призёр всероссийских соревнований по продуктовому программированию.",
                experience_years=3.5,
                soft_skills=["Работа в команде", "Менторство"],
                experience=[
                    {
                        "title": "Python-разработчик, ООО «Платёжные решения»",
                        "start": "03.2023",
                        "end": None,
                        "description": "FastAPI, PostgreSQL, Kafka, Docker",
                        "specialization": "backend",
                        "industry": "fintech",
                    }
                ],
                survey_completed_at=now - timedelta(days=10),
                industries=["fintech"],
                specialization="backend",
                stack=["Python", "FastAPI", "PostgreSQL", "Kafka", "Docker", "Redis", "Git", "REST"],
                work_formats=["remote", "hybrid"],
                salary_from=240000,
                salary_to=300000,
                search_status="active",
                claimed_grade="middle",
                confirmed_grade="middle",
                confirmed_at=now - timedelta(days=9),
                theta=0.55,
                theta_se=0.31,
                skill_scores={
                    **demo_src.skill_scores,
                    "python": {"status": "confirmed", "theta": 0.9, "se": 0.4, "n": 4, "n_correct": 4},
                    "sql": {"status": "confirmed", "theta": 0.7, "se": 0.42, "n": 4, "n_correct": 3},
                },
                fsp_id="FSP-000123",
                fsp_linked_at=now - timedelta(days=8),
                fsp_synced_at=now,
                fsp_achievements=ach,
                fsp_profile=fsp_profile,
                last_active_at=now,
            )
        )
        db.commit()
        n_cat = sum(1 for p in profiles if p.confirmed_grade)
        print(
            f"Готово: {len(profiles)} кандидатов ({n_cat} с категорией), {len(companies)} компаний, реестр ФСП {'доступен' if registry_ok else 'недоступен (локальные достижения)'}"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--candidates", type=int, default=300)
    args = ap.parse_args()
    if args.reset:
        reset()
    seed(args.candidates)


if __name__ == "__main__":
    main()
