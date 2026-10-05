"""Имитация реестра Федерации спортивного программирования.

Это *предложение команды* по составу данных, которые реестр ФСП мог бы отдавать платформе
(ТЗ: API и структура данных ФСП не предоставляются). Данные синтетические и детерминированы.

Сущности:
* Event — соревнование/мероприятие: дисциплина, уровень, даты, организатор;
* Participant — участник с ФСП ID, регионом, спортивным разрядом/званием;
* Result — результат участника: статус (победитель/призёр/финалист/участник), место,
  роль в команде, название команды.

Интеграция: платформа получает fsp_id из ФСП ID (OIDC claim) и запрашивает участника;
для периодической синхронизации — дельта по `changed_since`.
"""

from __future__ import annotations

import os
import random
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

API_KEY = os.environ.get("FSP_REGISTRY_API_KEY", "fsp-registry-demo-key")

Discipline = Literal["algorithmic", "product", "security", "robotics", "uav"]
Level = Literal["international", "national", "regional", "local"]
ResultStatus = Literal["winner", "prize", "finalist", "participant"]


class Event(BaseModel):
    id: str
    title: str
    discipline: Discipline
    level: Level
    start_date: date
    end_date: date
    city: str | None
    organizer: str


class Achievement(BaseModel):
    id: str
    event_id: str
    event: str
    discipline: Discipline
    level: Level
    result: ResultStatus
    place: int | None
    date: date
    role: str | None
    team: str | None


class Participant(BaseModel):
    fsp_id: str
    full_name: str
    region: str
    sport_rank: str | None
    updated_at: datetime
    achievements: list[Achievement]


class ParticipantPage(BaseModel):
    total: int
    items: list[Participant]


DISC_TITLES = {
    "algorithmic": "алгоритмическому программированию",
    "product": "продуктовому программированию",
    "security": "программированию систем информационной безопасности",
    "robotics": "программированию робототехники",
    "uav": "программированию беспилотных авиационных систем",
}
LEVEL_PREFIX = {
    "international": ["Международные соревнования по", "Открытый международный кубок по"],
    "national": ["Чемпионат России по", "Кубок России по", "Всероссийские соревнования по"],
    "regional": ["Чемпионат {region} по", "Первенство {region} по"],
    "local": ["Городские соревнования по", "Хакатон-отбор по"],
}
REGIONS = [
    "Москвы",
    "Санкт-Петербурга",
    "Республики Татарстан",
    "Новосибирской области",
    "Свердловской области",
    "Томской области",
    "Самарской области",
    "Краснодарского края",
]
REGION_NAMES = [
    "Москва",
    "Санкт-Петербург",
    "Республика Татарстан",
    "Новосибирская область",
    "Свердловская область",
    "Томская область",
    "Самарская область",
    "Краснодарский край",
]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Томск", "Самара", "Сочи"]
ROLES = ["backend", "frontend", "mobile", "ml", "devops", "аналитик", "капитан", "тестировщик"]
RANKS = [None, None, None, "3 разряд", "2 разряд", "1 разряд", "КМС", "МС"]
FIRST = [
    "Алексей",
    "Мария",
    "Иван",
    "Анна",
    "Дмитрий",
    "Екатерина",
    "Сергей",
    "Ольга",
    "Никита",
    "Полина",
    "Артём",
    "Дарья",
    "Кирилл",
    "Софья",
]
LAST = [
    "Смирнов",
    "Кузнецов",
    "Попов",
    "Васильев",
    "Петров",
    "Соколов",
    "Морозов",
    "Волков",
    "Лебедев",
    "Новиков",
]


def _build(seed: int = 2026):
    rng = random.Random(seed)
    events: list[Event] = []
    today = date(2026, 10, 5)
    for i in range(60):
        disc = rng.choice(list(DISC_TITLES))
        level = rng.choices(list(LEVEL_PREFIX), [0.08, 0.35, 0.42, 0.15])[0]
        reg_i = rng.randrange(len(REGIONS))
        prefix = rng.choice(LEVEL_PREFIX[level]).format(region=REGIONS[reg_i])
        start = today - timedelta(days=rng.randint(20, 365 * 5))
        events.append(
            Event(
                id=f"EV-{i + 1:04d}",
                title=f"{prefix} {DISC_TITLES[disc]} {start.year}",
                discipline=disc,
                level=level,
                start_date=start,
                end_date=start + timedelta(days=rng.randint(1, 3)),
                city=rng.choice(CITIES),
                organizer="ФСП России"
                if level in ("national", "international")
                else f"Региональное отделение ФСП ({REGION_NAMES[reg_i]})",
            )
        )
    participants: dict[str, Participant] = {}
    for n in range(1, 401):
        fid = f"FSP-{n:06d}"
        female = rng.random() < 0.35
        name = (
            f"{rng.choice(LAST)}{'а' if female else ''} {rng.choice(FIRST[1::2] if female else FIRST[0::2])}"
        )
        k = rng.choice([0, 1, 1, 2, 2, 3, 4, 5])
        ach = []
        for j, ev in enumerate(rng.sample(events, k)):
            r = rng.choices(["winner", "prize", "finalist", "participant"], [0.08, 0.17, 0.3, 0.45])[0]
            place = (
                1
                if r == "winner"
                else rng.randint(2, 3)
                if r == "prize"
                else rng.randint(4, 30)
                if r == "finalist"
                else None
            )
            ach.append(
                Achievement(
                    id=f"{fid}-R{j + 1}",
                    event_id=ev.id,
                    event=ev.title,
                    discipline=ev.discipline,
                    level=ev.level,
                    result=r,
                    place=place,
                    date=ev.end_date,
                    role=rng.choice(ROLES),
                    team=f"Команда «{rng.choice(['Байт', 'Сигма', 'Вектор', 'Кодеры', 'Стек', 'Рекурсия'])}»",
                )
            )
        participants[fid] = Participant(
            fsp_id=fid,
            full_name=name,
            region=rng.choice(REGION_NAMES),
            sport_rank=rng.choice(RANKS),
            updated_at=datetime(2026, 10, 1) - timedelta(days=rng.randint(0, 200)),
            achievements=sorted(ach, key=lambda a: a.date, reverse=True),
        )
    # Демонстрационный участник (связан с демо-аккаунтом ФСП ID)
    demo_events = [e for e in events if e.discipline == "product" and e.level == "national"][:1] + [
        e for e in events if e.discipline == "algorithmic"
    ][:1]
    participants["FSP-000123"] = Participant(
        fsp_id="FSP-000123",
        full_name="Иванова Мария",
        region="Москва",
        sport_rank="КМС",
        updated_at=datetime(2026, 9, 30),
        achievements=[
            Achievement(
                id="FSP-000123-R1",
                event_id=demo_events[0].id,
                event=demo_events[0].title,
                discipline="product",
                level="national",
                result="prize",
                place=2,
                date=demo_events[0].end_date,
                role="backend",
                team="Команда «Сигма»",
            ),
            Achievement(
                id="FSP-000123-R2",
                event_id=demo_events[1].id,
                event=demo_events[1].title,
                discipline="algorithmic",
                level=demo_events[1].level,
                result="finalist",
                place=12,
                date=demo_events[1].end_date,
                role="капитан",
                team="Команда «Сигма»",
            ),
        ],
    )
    return {e.id: e for e in events}, participants


EVENTS, PARTICIPANTS = _build()

app = FastAPI(
    title="Реестр ФСП (имитация)",
    version="0.1.0",
    description="Предложенная командой схема данных реестра Федерации спортивного программирования для интеграции с платформой подбора. "
    "Аутентификация сервис-сервис: заголовок `X-API-Key`.",
)


def require_key(x_api_key: str | None = Header(default=None)):
    if x_api_key != API_KEY:
        raise HTTPException(401, "invalid api key")


@app.get("/health")
def health():
    return {"status": "ok", "participants": len(PARTICIPANTS), "events": len(EVENTS)}


@app.get(
    "/api/v1/participants/{fsp_id}",
    response_model=Participant,
    dependencies=[Depends(require_key)],
    summary="Участник и его результаты",
)
def participant(fsp_id: str):
    p = PARTICIPANTS.get(fsp_id)
    if p is None:
        raise HTTPException(404, "participant not found")
    return p


@app.get(
    "/api/v1/participants",
    response_model=ParticipantPage,
    dependencies=[Depends(require_key)],
    summary="Дельта для синхронизации: участники, изменённые после даты",
)
def participants(changed_since: datetime | None = None, limit: int = Query(100, le=500), offset: int = 0):
    rows = sorted(PARTICIPANTS.values(), key=lambda p: p.updated_at)
    if changed_since:
        rows = [p for p in rows if p.updated_at > changed_since.replace(tzinfo=None)]
    return ParticipantPage(total=len(rows), items=rows[offset : offset + limit])


@app.get(
    "/api/v1/events",
    response_model=list[Event],
    dependencies=[Depends(require_key)],
    summary="Справочник соревнований",
)
def events(discipline: Discipline | None = None, level: Level | None = None):
    rows = list(EVENTS.values())
    if discipline:
        rows = [e for e in rows if e.discipline == discipline]
    if level:
        rows = [e for e in rows if e.level == level]
    return sorted(rows, key=lambda e: e.start_date, reverse=True)
