from __future__ import annotations

import os

os.environ.update(
    {
        "DATABASE_URL": "sqlite:///:memory:",
        "AUTH_MODE": "dev",
        "EMAIL_ENABLED": "false",
        "FSP_DISABLE_BACKGROUND": "1",
        "FSP_EMBEDDINGS": "hashing",
        "INVITE_QUOTA_PER_WEEK": "3",
        "LLM_ENABLED": "0",  # тесты не ходят во внешний LLM
    }
)

from types import SimpleNamespace  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import Base, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.assessment import service as assessment_service  # noqa: E402
from app.modules.employers import webhooks  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _db():
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)
    assessment_service.reset_engine_cache()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


class Api:
    def __init__(self, client: TestClient, email: str):
        self.c = client
        tok = client.post("/api/dev/login", json={"email": email}).json()["access_token"]
        self.h = {"Authorization": f"Bearer {tok}"}

    def get(self, url, **kw):
        return self.c.get(url, headers=self.h, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self.h, **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers=self.h, **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self.h, **kw)


SURVEY = {
    "industries": ["fintech"],
    "specialization": "backend",
    "stack": ["Python", "PostgreSQL", "FastAPI", "Docker", "постгрес"],
    "work_formats": ["remote", "hybrid"],
    "salary_from": 220000,
    "salary_to": 280000,
    "search_status": "active",
    "claimed_grade": "middle",
}


def make_candidate(client, email="cand@example.ru", publish=True, survey=None) -> Api:
    api = Api(client, email)
    r = api.post(
        "/api/me/role",
        json={"role": "candidate", "accept_pd_processing": True, "accept_profile_publication": publish},
    )
    assert r.status_code == 200, r.text
    r = api.put(
        "/api/candidate/profile",
        json={
            "full_name": "Иванова Мария Сергеевна",
            "phone": "+79161234567",
            "telegram": "@mivanova",
            "city": "Москва",
            "headline": "Python-разработчик",
            "about": "Пишу API на FastAPI",
        },
    )
    assert r.status_code == 200, r.text
    r = api.put("/api/candidate/survey", json=survey or SURVEY)
    assert r.status_code == 200, r.text
    return api


def make_employer(client, email="hr@example.ru", name="ООО «Тест»") -> Api:
    api = Api(client, email)
    r = api.post("/api/me/role", json={"role": "employer", "accept_pd_processing": True})
    assert r.status_code == 200, r.text
    r = api.put(
        "/api/employer/company", json={"name": name, "industry": "ecommerce", "description": "Маркетплейс"}
    )
    assert r.status_code == 200, r.text
    return api


def pass_test(api: Api, grade="middle", correct=True) -> dict:
    """Проходит адаптивный тест, отвечая верно (или неверно) — правильный ответ берём из движка."""
    from app.core.db import SessionLocal

    r = api.post("/api/assessment/attempts", json={"grade": grade})
    assert r.status_code == 201, r.text
    att = r.json()
    while att["status"] == "in_progress":
        item = att["item"]
        if item["kind"] in ("scenario", "probe"):
            from app.modules.assessment.models import AttemptItem
            from sqlalchemy import select

            with SessionLocal() as db:
                it = db.scalar(
                    select(AttemptItem).where(
                        AttemptItem.attempt_id == __import__("uuid").UUID(att["id"]),
                        AttemptItem.position == item["position"],
                    )
                )
                from app.modules.assessment.models import Attempt

                inst = assessment_service.scenario_instance(db.get(Attempt, it.attempt_id), it)
            if correct:
                # «эталонный» ответ: ожидания рубрики и ключевые термины (резервная оценка без LLM)
                if item["kind"] == "scenario":
                    value = "\n".join(f"{c.title}: {c.expect}. {c.strong}." for c in inst.criteria) * 2
                else:
                    pr = inst.probe((it.meta or {}).get("probe", 0))
                    value = f"{pr.expect}. " + " ".join(
                        k.replace("\\", "").split("|")[0] for k in pr.keywords
                    )
            else:
                value = "Не знаю."
            r = api.post(
                f"/api/assessment/attempts/{att['id']}/answer",
                json={"position": item["position"], "value": value, "time_ms": 60000},
            )
            assert r.status_code == 200, r.text
            att = r.json()
            continue
        with SessionLocal() as db:
            eng = assessment_service.get_engine(db)
            from app.modules.assessment.models import AttemptItem
            from sqlalchemy import select

            it = db.scalar(
                select(AttemptItem).where(
                    AttemptItem.attempt_id == __import__("uuid").UUID(att["id"]),
                    AttemptItem.position == item["position"],
                )
            )
            inst = eng.regenerate(att["id"], it.position, it.family_id)
        value = (
            inst.answer
            if correct
            else (
                "__wrong__"
                if inst.kind == "text"
                else (
                    -12345
                    if inst.kind == "number"
                    else ((inst.answer + 1) % len(inst.options) if inst.kind == "single" else [])
                )
            )
        )
        r = api.post(
            f"/api/assessment/attempts/{att['id']}/answer",
            json={"position": item["position"], "value": value, "time_ms": 5000},
        )
        assert r.status_code == 200, r.text
        att = r.json()
    return att


def capture_webhooks(monkeypatch) -> list[tuple[str, dict]]:
    """Подменить HTTP-клиент вебхуков: запросы складываются в список (url, kwargs)."""
    sent: list[tuple[str, dict]] = []

    class _Client:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, url, **kw):
            sent.append((url, kw))

    monkeypatch.setattr(webhooks, "httpx", SimpleNamespace(Client=_Client, HTTPError=httpx.HTTPError))
    return sent
