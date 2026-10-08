"""Второй этап теста (практический кейс + уточняющий вопрос) и надёжность прохождения."""

from __future__ import annotations

import uuid

from app.modules.assessment import service as assessment_service
from app.modules.assessment.models import Attempt, AttemptItem
from sqlalchemy import select

from tests.conftest import make_candidate


def _db_item(att: dict):
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        it = db.scalar(
            select(AttemptItem).where(
                AttemptItem.attempt_id == uuid.UUID(att["id"]),
                AttemptItem.position == att["item"]["position"],
            )
        )
        a = db.get(Attempt, it.attempt_id)
        if it.kind == "item":
            return it, assessment_service.get_engine(db).regenerate(att["id"], it.position, it.family_id)
        return it, assessment_service.scenario_instance(a, it)


def _answer(api, att: dict, value=None, *, correct=True, **signals) -> dict:
    it, inst = _db_item(att)
    if value is None:
        if it.kind == "item":
            value = inst.answer if correct else "__wrong__"
        elif it.kind == "scenario":
            value = (
                "\n".join(f"{c.title}: {c.expect}. {c.strong}." for c in inst.criteria) * 2
                if correct
                else "Не знаю."
            )
        else:
            pr = inst.probe((it.meta or {}).get("probe", 0))
            value = pr.expect if correct else "Не знаю."
    r = api.post(
        f"/api/assessment/attempts/{att['id']}/answer",
        json={"position": att["item"]["position"], "value": value, "time_ms": 4000, **signals},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _run_knowledge(api, att: dict) -> dict:
    while att["status"] == "in_progress" and att["item"]["stage"] == "knowledge":
        att = _answer(api, att)
    return att


def test_middle_has_scenario_and_probe_stage(client):
    cand = make_candidate(client)
    att = cand.post("/api/assessment/attempts", json={"grade": "middle"}).json()
    assert att["has_scenario"] and att["integrity"]["leaves_left"] == 3
    att = _run_knowledge(cand, att)
    assert att["status"] == "in_progress" and att["item"]["kind"] == "scenario"
    assert att["item"]["task"] and att["item"]["time_limit"] >= 600
    att = _answer(cand, att)
    assert att["item"]["kind"] == "probe" and "Уточняющий вопрос" in att["item"]["prompt"]
    assert att["item"]["time_limit"] == 120
    att = _answer(cand, att)
    assert att["status"] == "passed"
    sc = att["result"]["scenario"]
    assert sc and sc["category"] >= 2 and sc["method"] == "keywords" and sc["probe"]["question"]
    assert att["result"]["integrity"]["level"] == "clean"
    prof = cand.get("/api/candidate/profile").json()
    assert prof["confirmed_grade"] == "middle"


def test_junior_has_no_scenario(client):
    cand = make_candidate(client)
    att = cand.post("/api/assessment/attempts", json={"grade": "junior"}).json()
    assert not att["has_scenario"]
    att = _run_knowledge(cand, att)
    assert att["status"] == "passed" and att["result"]["scenario"] is None


def test_weak_scenario_lowers_confidence(client):
    cand = make_candidate(client)
    att = cand.post("/api/assessment/attempts", json={"grade": "middle"}).json()
    att = _run_knowledge(cand, att)
    att = _answer(cand, att, correct=False)
    att = _answer(cand, att, correct=False)
    res = att["result"]
    assert res["scenario"]["category"] == 0
    assert res["p_claimed"] < res["knowledge_p_claimed"]


def test_leaving_page_voids_attempt(client):
    cand = make_candidate(client)
    att = cand.post("/api/assessment/attempts", json={"grade": "middle"}).json()
    att = _answer(cand, att, tab_switches=1, away_ms=8000)
    assert att["status"] == "in_progress" and att["integrity"]["leaves_left"] == 2
    att = _answer(cand, att, tab_switches=2, away_ms=15000)
    att = _answer(cand, att, tab_switches=1, away_ms=3000)
    assert att["status"] == "voided"
    assert att["result"]["decision"] == "voided" and "аннулирована" in att["result"]["explanation"][0]
    # аннулированная = неудачная: тот же уровень — через 14 дней, ниже — сразу
    assert cand.post("/api/assessment/attempts", json={"grade": "middle"}).status_code == 409
    assert cand.post("/api/assessment/attempts", json={"grade": "junior"}).status_code == 201


def test_short_leaves_ignored_single_leave_flagged(client):
    cand = make_candidate(client)
    att = cand.post("/api/assessment/attempts", json={"grade": "junior"}).json()
    att = _answer(cand, att, tab_switches=1, away_ms=900)  # < 2 с — не сигнал
    assert att["integrity"]["leaves_left"] == 3
    att = _answer(cand, att, tab_switches=1, away_ms=6000, paste_attempts=1)
    att = _run_knowledge(cand, att)
    assert att["status"] == "passed"
    integ = att["result"]["integrity"]
    assert integ["level"] == "review" and integ["items_left"] == 1 and integ["paste_attempts"] == 1


def _families(att_id: str) -> set[str]:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        return set(
            db.scalars(
                select(AttemptItem.family_id).where(
                    AttemptItem.attempt_id == uuid.UUID(att_id), AttemptItem.kind == "item"
                )
            ).all()
        )


def test_next_attempt_avoids_seen_families(client):
    """Тест на уровень ниже после неудачи идёт на других семействах, а не на тех же с другими числами."""
    from tests.conftest import pass_test

    cand = make_candidate(client)
    first = pass_test(cand, "middle", correct=False)
    assert first["status"] == "failed"
    second = pass_test(cand, "junior")
    seen, now = _families(first["id"]), _families(second["id"])
    assert seen and now
    assert not seen & now, f"повторились семейства: {seen & now}"


def test_case_follows_direction_and_industry(client):
    """CV-специалист из спорта получает кейс про видео матчей, а не про отток клиентов банка."""
    from tests.conftest import SURVEY

    survey = {
        **SURVEY,
        "specialization": "data_science",
        "industries": ["sport"],
        "directions": ["cv"],
        "stack": ["Python", "PyTorch"],
    }
    cand = make_candidate(client, survey=survey)
    assert cand.get("/api/candidate/profile").json()["directions"] == ["cv"]
    elig = cand.get("/api/assessment/eligibility").json()
    assert "cv" in elig["blueprint"]["weights"]
    att = _run_knowledge(cand, cand.post("/api/assessment/attempts", json={"grade": "middle"}).json())
    assert att["item"]["kind"] == "scenario"
    assert "фол" in att["item"]["prompt"].lower() and "банк" not in att["item"]["prompt"].lower()
    att = _answer(cand, att)
    assert "фол" in att["item"]["prompt"].lower()  # уточняющий вопрос — по той же версии кейса
    att = _answer(cand, att)
    assert att["result"]["scenario"]["title"].startswith("Детектор фолов")


def test_unknown_direction_rejected(client):
    from tests.conftest import SURVEY

    cand = make_candidate(client)
    r = cand.put("/api/candidate/survey", json={**SURVEY, "directions": ["cv"]})  # у backend нет направлений
    assert r.status_code == 422


def test_environment_and_fullscreen_signals(client):
    """Удалённый рабочий стол (по видеоадаптеру), второй монитор и выход из полноэкранного режима —
    пометки для работодателя; три задания вне полноэкранного режима — аннулирование."""
    cand = make_candidate(client)
    env = {
        "renderer": "ANGLE (Microsoft, Microsoft Remote Display Adapter)",
        "webdriver": False,
        "fullscreen": True,
    }
    att = cand.post("/api/assessment/attempts", json={"grade": "junior", "env": env}).json()
    att = _answer(cand, att, fullscreen_off_ms=4000, fullscreen_exits=1)
    att = _answer(cand, att, extended_screen=True)
    att = _run_knowledge(cand, att)
    assert att["status"] == "passed"
    reasons = " ".join(att["result"]["integrity"]["reasons"])
    assert (
        "полноэкранного" in reasons and "удалённого рабочего стола" in reasons and "второй монитор" in reasons
    )
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        assert db.get(Attempt, uuid.UUID(att["id"])).env["virtual"] == "rdp"  # классифицирует сервер

    cand2 = make_candidate(client, email="c2@example.ru")
    att = cand2.post("/api/assessment/attempts", json={"grade": "junior"}).json()
    for _ in range(3):
        att = _answer(cand2, att, fullscreen_off_ms=5000)
    assert att["status"] == "voided"


def _age_current_item(att: dict, seconds: int) -> None:
    from datetime import timedelta

    from app.core.db import SessionLocal

    with SessionLocal() as db:
        it = db.scalar(
            select(AttemptItem).where(
                AttemptItem.attempt_id == uuid.UUID(att["id"]),
                AttemptItem.position == att["item"]["position"],
            )
        )
        it.issued_at = it.issued_at - timedelta(seconds=seconds)
        db.commit()


def test_overtime_answer_counts_and_is_marked(client):
    """Время на задание — ориентир: ответ после него засчитывается, задание помечается."""
    cand = make_candidate(client)
    att = cand.post("/api/assessment/attempts", json={"grade": "junior"}).json()
    limit = att["item"]["time_limit"]
    _age_current_item(att, limit + assessment_service.TIME_GRACE_SEC + 60)
    pos = att["item"]["position"]
    att = _answer(cand, att)
    it, _ = _db_item({**att, "item": {"position": pos}})
    assert it.correct is True
    assert it.response["overtime"] is True and it.response["overtime_sec"] >= 60
    att = _run_knowledge(cand, att)
    pace = att["result"]["pace"]
    assert pace["overtime_items"] == 1 and pace["items"] == att["result"]["n_items"]
