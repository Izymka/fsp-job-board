"""ФСП-доработки: вакансии «открыты для ФСП», «что доказывает достижение», план роста."""

from __future__ import annotations

from tests.conftest import SURVEY, Api, make_candidate, make_employer, pass_test

ACH = {
    "id": "a1",
    "event": "Всероссийские соревнования по продуктовому программированию",
    "discipline": "product",
    "level": "national",
    "result": "prize",
    "place": 2,
    "date": "2026-04-10",
    "role": "backend",
    "team": "Сигма",
}


def _registry(monkeypatch, achievements=(ACH,)):
    from app.modules.fsp import router as fsp_router

    data = {"fsp_id": "FSP-000123", "full_name": "Иванова М.С.", "achievements": list(achievements)}
    monkeypatch.setattr(fsp_router, "fetch_participant", lambda fid: data if fid == "FSP-000123" else None)
    return fsp_router


def test_fsp_friendly_vacancy_badge_filter_and_partner(client):
    emp = make_employer(client)
    body = {
        "title": "Python-разработчик (Junior)",
        "text": "Разработка сервисов на Python и FastAPI, PostgreSQL. Опыт от 1 года.",
        "salary_from": 100000,
        "salary_to": 140000,
    }
    plain = emp.post("/api/employer/vacancies", json=body).json()
    open_ = emp.post("/api/employer/vacancies", json={**body, "fsp_friendly": True}).json()
    assert open_["fsp_friendly"] and not plain["fsp_friendly"]
    cand = make_candidate(client)
    pass_test(cand, grade="junior")
    feed = cand.get("/api/vacancies").json()
    assert {v["id"] for v in feed} == {plain["id"], open_["id"]}
    assert all(v["company_fsp_partner"] for v in feed)  # у компании есть открытая для ФСП вакансия
    only = cand.get("/api/vacancies?fsp_friendly=true").json()
    assert [v["id"] for v in only] == [open_["id"]]
    # снятие флага — компания перестаёт быть партнёром
    emp.put(f"/api/employer/vacancies/{open_['id']}", json=body)
    assert not any(v["company_fsp_partner"] for v in cand.get("/api/vacancies").json())


def test_search_fsp_settings(client):
    emp = make_employer(client)
    s = emp.post(
        "/api/employer/searches",
        json={
            "title": "Backend",
            "text": "Python FastAPI",
            "specialization": "backend",
            "grade": "junior",
            "notify_fsp": True,
        },
    ).json()
    assert s["search"]["notify_fsp"] and not s["search"]["fsp_friendly"]
    upd = emp.put(
        f"/api/employer/searches/{s['search']['id']}/fsp", json={"fsp_friendly": True, "notify_fsp": False}
    )
    assert upd.status_code == 200 and upd.json()["fsp_friendly"] and not upd.json()["notify_fsp"]


def test_project_link_survives_sync_and_reaches_card(client, monkeypatch):
    _registry(monkeypatch)
    cand = make_candidate(client)
    pass_test(cand)
    cand.post("/api/fsp/link/demo", json={"fsp_id": "FSP-000123"})
    bad = cand.put("/api/fsp/achievements/a1/project", json={"url": "javascript:alert(1)"})
    assert bad.status_code == 422
    assert cand.put("/api/fsp/achievements/nope/project", json={"url": "https://x.ru"}).status_code == 404
    r = cand.put("/api/fsp/achievements/a1/project", json={"url": "https://github.com/sigma/app"})
    assert r.json()["fsp_achievements"][0]["project_url"] == "https://github.com/sigma/app"
    cand.post("/api/fsp/sync")  # реестр не знает ссылок — после обновления ссылка остаётся
    prof = cand.get("/api/candidate/profile").json()
    assert prof["fsp_achievements"][0]["project_url"] == "https://github.com/sigma/app"
    emp = make_employer(client)
    s = emp.post(
        "/api/employer/searches",
        json={"title": "Backend", "text": "Python FastAPI", "specialization": "backend", "grade": "middle"},
    ).json()
    item = s["results"][0]["card"]["fsp"][0]
    assert (
        item["team"] == "Сигма"
        and item["place"] == 2
        and item["project_url"] == "https://github.com/sigma/app"
    )


def test_growth_plan_relevant_events_and_registry_down(client, monkeypatch):
    fsp_router = _registry(monkeypatch)
    events = [
        {
            "id": "U1",
            "title": "Кубок по продуктовому",
            "discipline": "product",
            "level": "national",
            "start_date": "2026-12-01",
            "city": "Казань",
        },
        {
            "id": "U2",
            "title": "Кубок по робототехнике",
            "discipline": "robotics",
            "level": "regional",
            "start_date": "2026-11-01",
            "city": None,
        },
    ]
    monkeypatch.setattr(fsp_router, "fetch_upcoming_events", lambda: events)
    cand = make_candidate(client)
    pass_test(cand, correct=False)
    g = cand.get("/api/fsp/growth").json()
    # обе дисциплины релевантны backend (продуктовое 1.0, робототехника 0.5 — на пороге), порядок — по дате
    assert [e["id"] for e in g["events"]] == ["U2", "U1"] and g["registry_available"]
    assert g["weak_skills"]  # после проваленного теста есть что подтянуть
    # для аналитика робототехника (0.2) не предлагается
    an = make_candidate(
        client, "an@example.ru", survey={**SURVEY, "specialization": "analyst", "stack": ["SQL"]}
    )
    assert [e["id"] for e in an.get("/api/fsp/growth").json()["events"]] == ["U1"]

    def down():
        raise fsp_router.RegistryUnavailable("timeout")

    monkeypatch.setattr(fsp_router, "fetch_upcoming_events", down)
    g = cand.get("/api/fsp/growth").json()
    assert g["events"] == [] and not g["registry_available"]


def test_fsp_alert_digest_once_per_pair_and_day(client, monkeypatch):
    from app.modules.employers import fsp_alerts

    _registry(monkeypatch)
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(fsp_alerts, "send_email", lambda to, subj, body: sent.append((to, subj, body)))
    emp = make_employer(client)
    s = emp.post(
        "/api/employer/searches",
        json={
            "title": "Backend",
            "text": "Python FastAPI PostgreSQL",
            "specialization": "backend",
            "grade": "middle",
            "notify_fsp": True,
        },
    ).json()
    quiet = emp.post(
        "/api/employer/searches",
        json={"title": "Без уведомлений", "text": "Python", "specialization": "backend", "grade": "middle"},
    ).json()
    # участник ФСП без подтверждённого грейда — ещё не повод для уведомления
    a = make_candidate(client, "a@example.ru")
    a.post("/api/fsp/link/demo", json={"fsp_id": "FSP-000123"})
    assert not sent
    pass_test(a)  # подтвердил грейд → попал в топ подборки → письмо
    assert len(sent) == 1 and "Новые участники ФСП" in sent[0][1] and s["search"]["id"] in sent[0][2]
    assert "Иванова" not in sent[0][2] and "+7916" not in sent[0][2]  # без ПДн, только анонимная карточка
    a.post("/api/fsp/sync")  # повторное событие по той же паре — без нового письма
    assert len(sent) == 1
    # второй участник ФСП в тот же день — запись есть, письмо ждёт суток
    from app.core.db import SessionLocal
    from app.modules.employers.models import FspMatchNotice

    data = {"fsp_id": "FSP-000124", "achievements": [{**ACH, "id": "b1"}]}
    from app.modules.fsp import router as fsp_router

    monkeypatch.setattr(fsp_router, "fetch_participant", lambda fid: data if fid == "FSP-000124" else None)
    b = make_candidate(client, "b@example.ru")
    pass_test(b)
    b.post("/api/fsp/link/demo", json={"fsp_id": "FSP-000124"})
    with SessionLocal() as db:
        rows = db.query(FspMatchNotice).all()
        assert len(rows) == 2 and {str(r.search_id) for r in rows} == {s["search"]["id"]}
        assert sum(r.emailed_at is None for r in rows) == 1
        assert quiet["search"]["id"] not in {str(r.search_id) for r in rows}
    assert len(sent) == 1


def test_fsp_alert_repeat_and_race_do_not_duplicate_notice(client, monkeypatch):
    import pytest
    from app.core.db import SessionLocal
    from app.modules.assessment.service import notify_fsp_alerts
    from app.modules.candidates.models import CandidateProfile
    from app.modules.employers import fsp_alerts
    from app.modules.employers.models import FspMatchNotice
    from sqlalchemy.exc import IntegrityError

    fsp_router = _registry(monkeypatch)
    monkeypatch.setattr(fsp_alerts, "send_email", lambda *a: None)
    emp = make_employer(client)
    emp.post(
        "/api/employer/searches",
        json={
            "title": "Backend",
            "text": "Python FastAPI PostgreSQL",
            "specialization": "backend",
            "grade": "middle",
            "notify_fsp": True,
        },
    )
    a = make_candidate(client, "a@example.ru")
    a.post("/api/fsp/link/demo", json={"fsp_id": "FSP-000123"})
    pass_test(a)
    with SessionLocal() as db:
        (first,) = db.query(FspMatchNotice).all()
        p = db.get(CandidateProfile, first.candidate_id)
        # повторное событие по той же паре (второй воркер, повторная синхронизация)
        assert fsp_alerts.on_fsp_candidate_update(db, p) == []
        notify_fsp_alerts(db, p)
        db.commit()
        assert db.query(FspMatchNotice).count() == 1
        # гонка мимо проверки в коде: дубль отсекает уникальное ограничение
        db.add(FspMatchNotice(search_id=first.search_id, candidate_id=p.user_id, rank=1, reason=""))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        assert db.query(FspMatchNotice).count() == 1
        assert fsp_router._sync_leader(db)  # SQLite: без блокировки, итерация идёт как раньше


def test_hired_status_keeps_contacts_and_feeds_funnel(client, monkeypatch):
    _registry(monkeypatch)
    cand = make_candidate(client)
    pass_test(cand)
    cand.post("/api/fsp/link/demo", json={"fsp_id": "FSP-000123"})
    emp = make_employer(client)
    cid = cand.get("/api/me").json()["id"]
    inv = emp.post(
        "/api/employer/invitations",
        json={
            "candidate_id": cid,
            "title": "Python-разработчик",
            "description": "Команда платежей",
            "salary_from": 240000,
            "salary_to": 300000,
            "contact_method": "email",
            "contact_value": "hr@example.ru",
        },
    ).json()
    assert emp.post(f"/api/employer/invitations/{inv['id']}/hired").status_code == 409  # ещё не принято
    cand.post(f"/api/candidate/invitations/{inv['id']}/accept")
    r = emp.post(f"/api/employer/invitations/{inv['id']}/hired")
    assert r.status_code == 200 and r.json()["status"] == "hired"
    card = emp.get(f"/api/employer/candidates/{cid}").json()
    assert card["revealed"] and card["contacts"]  # выход на работу не закрывает контакты
    # воронка федерации: доступ только роли fsp_admin, группы меньше 5 скрыты
    assert emp.get("/api/fsp/funnel").status_code == 403
    fed = Api(client, "federation@demo.fsp")
    me = fed.get("/api/me").json()
    assert me["role"] == "fsp_admin" and me["onboarding_step"] == "done"
    f = fed.get("/api/fsp/funnel").json()
    assert f["fsp"]["counts"]["registered"] is None  # 1 участник — меньше порога, не раскрывается
    for i in range(5):
        c = make_candidate(client, f"f{i}@example.ru")
        monkeypatch.setattr(
            __import__("app.modules.fsp.router", fromlist=["x"]),
            "fetch_participant",
            lambda fid: {"fsp_id": fid, "achievements": [{**ACH, "id": fid}]},
        )
        assert c.post("/api/fsp/link/demo", json={"fsp_id": f"FSP-20000{i}"}).status_code == 200
    f = fed.get("/api/fsp/funnel").json()
    assert f["fsp"]["counts"]["registered"] == 6 and f["fsp"]["counts"]["survey"] == 6
    assert f["fsp"]["counts"]["hired"] is None  # 1 трудоустроенный — скрыт
    assert any(r["key"] == "national" for r in f["by_level"])
    assert "full_name" not in str(f) and "FSP-" not in str(f)
