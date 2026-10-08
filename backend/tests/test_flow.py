"""Сквозной сценарий из ТЗ §3.3 и правила видимости из §2.2."""

from __future__ import annotations

import io

from tests.conftest import SURVEY, Api, make_candidate, make_employer, pass_test


def test_unauthenticated_and_wrong_role(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me").json()["error"]["code"] == "unauthorized"
    cand = make_candidate(client)
    assert cand.get("/api/employer/searches").status_code == 403
    emp = make_employer(client)
    assert emp.get("/api/candidate/profile").status_code == 403
    assert client.get("/api/catalog").status_code == 200


def test_consent_required(client):
    api = Api(client, "x@example.ru")
    r = api.post("/api/me/role", json={"role": "candidate", "accept_pd_processing": False})
    assert r.status_code == 400 and r.json()["error"]["code"] == "consent_required"


def test_end_to_end_invitation_flow(client):
    cand = make_candidate(client)
    me = cand.get("/api/me").json()
    assert me["onboarding_step"] == "test"
    prof = cand.get("/api/candidate/profile").json()
    assert (
        "PostgreSQL" in prof["stack"] and prof["stack"].count("PostgreSQL") == 1
    )  # алиас «постгрес» нормализован

    elig = cand.get("/api/assessment/eligibility").json()
    assert all(o["allowed"] for o in elig["options"]) and elig["rules"]
    att = pass_test(cand, "middle", correct=True)
    assert att["status"] == "passed" and att["result"]["decision"] == "confirmed"
    assert att["result"]["suggestion"] == "upgrade"
    prof = cand.get("/api/candidate/profile").json()
    assert prof["confirmed_grade"] == "middle" and prof["category"] == "Backend · Middle"
    assert any(s["status"] == "confirmed" for s in prof["skill_scores"].values())
    # сразу после первого подтверждения доступно повышение на ступень (онбординг)
    elig = {o["grade"]: o for o in cand.get("/api/assessment/eligibility").json()["options"]}
    assert elig["senior"]["allowed"] and elig["senior"]["kind"] == "upgrade"
    assert not elig["lead"]["allowed"]

    emp = make_employer(client)
    r = emp.post(
        "/api/employer/searches",
        json={
            "title": "Python-разработчик (Middle)",
            "text": "Нужен бэкенд-разработчик: Python, FastAPI, PostgreSQL, Docker. Вилка 230-300 тыс ₽, удалённо.",
        },
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["search"]["specialization"] == "backend" and s["search"]["grade"] == "middle"
    assert s["base_total"] == 1
    top = s["results"][0]
    assert (
        top["card"]["revealed"] is False
        and top["card"]["full_name"] is None
        and top["card"]["contacts"] is None
    )
    assert any("Подтверждено тестом" in x["text"] for x in top["reasons"])
    assert any(c["relation"] == "target" and c["total"] == 1 for c in s["categories"])
    cid = top["card"]["id"]

    card = emp.get(f"/api/employer/candidates/{cid}").json()
    assert card["contacts"] is None and card["full_name"] is None
    chk = emp.get(
        "/api/employer/salary-check", params={"candidate_id": cid, "salary_from": 150000, "salary_to": 180000}
    ).json()
    assert chk["fit"] == "below"

    # вилка обязательна и валидируется
    bad = emp.post(
        "/api/employer/invitations",
        json={
            "candidate_id": cid,
            "title": "Backend",
            "description": "Описание предложения",
            "salary_from": 300000,
            "salary_to": 200000,
            "contact_method": "email",
            "contact_value": "hr@example.ru",
        },
    )
    assert bad.status_code == 422
    r = emp.post(
        "/api/employer/invitations",
        json={
            "candidate_id": cid,
            "search_id": s["search"]["id"],
            "title": "Python-разработчик",
            "description": "Платёжная платформа, команда 6 человек",
            "salary_from": 240000,
            "salary_to": 300000,
            "contact_method": "telegram",
            "contact_value": "@hr_test",
        },
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "sent" and inv["salary_fit"] == "within" and inv["candidate_contacts"] is None
    dup = emp.post(
        "/api/employer/invitations",
        json={
            "candidate_id": cid,
            "title": "Ещё раз",
            "description": "Повторное приглашение",
            "salary_from": 1,
            "salary_to": 2,
            "contact_method": "email",
            "contact_value": "a@b.ru",
        },
    )
    assert dup.status_code == 409

    lst = cand.get("/api/candidate/invitations").json()
    assert len(lst) == 1 and lst[0]["company_name"] == "ООО «Тест»" and lst[0]["salary_from"] == 240000
    assert cand.get(f"/api/candidate/invitations/{inv['id']}").json()["status"] == "viewed"
    assert emp.get("/api/employer/invitations").json()[0]["status"] == "viewed"
    acc = cand.post(f"/api/candidate/invitations/{inv['id']}/accept")
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    assert (
        cand.post(f"/api/candidate/invitations/{inv['id']}/decline", json={"reason": "salary"}).status_code
        == 409
    )

    card = emp.get(f"/api/employer/candidates/{cid}").json()
    assert (
        card["revealed"]
        and card["full_name"] == "Иванова Мария Сергеевна"
        and card["contacts"]["telegram"] == "@mivanova"
    )
    einv = emp.get("/api/employer/invitations").json()[0]
    assert einv["status"] == "accepted" and einv["candidate_contacts"]["phone"] == "+79161234567"
    ins = emp.get("/api/employer/insights").json()
    assert ins["invitations"]["accepted"] == 1 and ins["acceptance_rate"] == 1.0


def test_isolation_between_users(client):
    a = make_candidate(client, "a@example.ru")
    b = make_candidate(client, "b@example.ru")
    pass_test(a)
    e1 = make_employer(client, "e1@example.ru", "Альфа")
    e2 = make_employer(client, "e2@example.ru", "Бета")
    s = e1.post(
        "/api/employer/searches",
        json={
            "title": "Backend",
            "text": "Python, PostgreSQL",
            "specialization": "backend",
            "grade": "middle",
        },
    ).json()
    assert e2.get(f"/api/employer/searches/{s['search']['id']}").status_code == 404
    cid = s["results"][0]["card"]["id"]
    inv = e1.post(
        "/api/employer/invitations",
        json={
            "candidate_id": cid,
            "title": "Backend",
            "description": "Описание предложения",
            "salary_from": 200000,
            "salary_to": 250000,
            "contact_method": "email",
            "contact_value": "hr@a.ru",
        },
    ).json()
    assert b.get(f"/api/candidate/invitations/{inv['id']}").status_code == 404
    assert b.post(f"/api/candidate/invitations/{inv['id']}/accept").status_code == 404
    assert e2.post(f"/api/employer/invitations/{inv['id']}/withdraw").status_code == 404
    att = a.get("/api/assessment/attempts").json()[0]
    assert b.get(f"/api/assessment/attempts/{att['id']}").status_code == 404
    # кандидат без подтверждённого грейда не виден работодателю
    bid = b.get("/api/candidate/profile").json()["user_id"]
    assert e1.get(f"/api/employer/candidates/{bid}").status_code == 404


def test_failed_attempt_cooldown_and_abandon(client):
    cand = make_candidate(client)
    att = pass_test(cand, "senior", correct=False)
    assert att["status"] == "failed" and att["result"]["suggestion"] == "downgrade"
    r = cand.post("/api/assessment/attempts", json={"grade": "senior"})
    assert r.status_code == 409 and r.json()["error"]["details"]["available_at"]
    assert cand.post("/api/assessment/attempts", json={"grade": "lead"}).status_code == 409
    r = cand.post("/api/assessment/attempts", json={"grade": "middle"})
    assert r.status_code == 201
    assert (
        cand.post("/api/assessment/attempts", json={"grade": "junior"}).status_code == 409
    )  # одна активная попытка
    ab = cand.post(f"/api/assessment/attempts/{r.json()['id']}/abandon").json()
    assert ab["status"] == "abandoned"
    assert cand.post("/api/assessment/attempts", json={"grade": "middle"}).status_code == 409
    assert cand.post("/api/assessment/attempts", json={"grade": "junior"}).status_code == 201


def test_answer_position_and_no_answer_leak(client):
    cand = make_candidate(client)
    att = cand.post("/api/assessment/attempts", json={"grade": "middle"}).json()
    assert "answer" not in att["item"]
    r = cand.post(f"/api/assessment/attempts/{att['id']}/answer", json={"position": 5, "value": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "wrong_position"


def test_quota_and_hidden_profile(client):
    emp = make_employer(client)
    ids = []
    for i in range(4):
        c = make_candidate(client, f"c{i}@example.ru")
        pass_test(c)
        ids.append(c.get("/api/candidate/profile").json()["user_id"])
    for i, cid in enumerate(ids):
        r = emp.post(
            "/api/employer/invitations",
            json={
                "candidate_id": cid,
                "title": "Backend",
                "description": "Описание предложения",
                "salary_from": 200000,
                "salary_to": 250000,
                "contact_method": "email",
                "contact_value": "hr@a.ru",
            },
        )
        assert r.status_code == (201 if i < 3 else 429), r.text
    # отзыв согласия на публикацию скрывает профиль из поиска
    c0 = make_candidate(client, "c0@example.ru")
    c0.post("/api/me/consents", json={"kind": "profile_publication", "accepted": False})
    bank = emp.get("/api/employer/candidates", params={"specialization": "backend"}).json()
    assert bank["total"] == 3 and all(x["revealed"] is False or x["contacts"] for x in bank["items"])


def test_vacancy_and_application_reveal_contacts(client):
    emp = make_employer(client)
    bad = emp.post(
        "/api/employer/vacancies",
        json={
            "title": "Backend",
            "text": "Python-разработчик в команду платежей",
            "salary_from": 0,
            "salary_to": 100,
        },
    )
    assert bad.status_code == 422
    v = emp.post(
        "/api/employer/vacancies",
        json={
            "title": "Python-разработчик (Middle)",
            "text": "Разработка сервисов на Python и FastAPI, PostgreSQL, Docker. Опыт от 2 лет.",
            "salary_from": 200000,
            "salary_to": 260000,
            "work_format": "remote",
        },
    )
    assert v.status_code == 201, v.text
    vac = v.json()
    assert vac["specialization"] == "backend" and vac["grade"] == "middle" and vac["blueprint"]
    cand = make_candidate(client)
    pass_test(cand)
    feed = cand.get("/api/vacancies").json()
    assert feed[0]["id"] == vac["id"] and feed[0]["match"]["score"] > 0
    ap = cand.post(f"/api/vacancies/{vac['id']}/apply", json={"cover_letter": "Хочу к вам"})
    assert ap.status_code == 201
    assert cand.post(f"/api/vacancies/{vac['id']}/apply", json={}).status_code == 409
    apps = emp.get(f"/api/employer/vacancies/{vac['id']}/applications").json()
    assert apps[0]["candidate"]["revealed"] and apps[0]["candidate"]["contacts"]["phone"] == "+79161234567"
    st = emp.post(f"/api/employer/applications/{apps[0]['id']}/status", json={"status": "interview"}).json()
    assert st["status"] == "interview"
    assert cand.get("/api/candidate/applications").json()[0]["status"] == "interview"


def test_regular_tasks(client):
    emp = make_employer(client)
    t = emp.post(
        "/api/employer/tasks",
        json={"title": "SQL-разминка", "kind": "auto", "specialization": "backend", "skill": "sql"},
    )
    assert t.status_code == 201, t.text
    cand = make_candidate(client)
    pass_test(cand)
    tasks = cand.get("/api/candidate/tasks").json()
    assert len(tasks) == 1 and tasks[0]["status"] == "assigned" and tasks[0]["prompt"]
    r = cand.post(f"/api/candidate/tasks/{tasks[0]['id']}/submit", json={"value": "0"})
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    prof = cand.get("/api/candidate/profile").json()
    assert prof["tasks_score"] >= 0
    subs = emp.get(f"/api/employer/tasks/{t.json()['id']}/submissions").json()
    assert len(subs) == 1 and subs[0]["candidate_alias"]


def test_resume_upload_and_pdf(client):
    import random

    from fspml.validation.resume import make_resume

    cand = make_candidate(client)
    truth, pdf = make_resume(random.Random(3))
    r = cand.post("/api/candidate/resume", files={"file": ("cv.pdf", io.BytesIO(pdf), "application/pdf")})
    assert r.status_code == 200, r.text
    sug = r.json()["suggestions"]
    assert sug["full_name"] == truth.name and sug["contact_email"] == truth.email
    assert set(truth.skills) <= set(r.json()["parsed"]["skills"])
    bad = cand.post(
        "/api/candidate/resume", files={"file": ("cv.docx", io.BytesIO(b"PK.."), "application/octet-stream")}
    )
    assert bad.status_code == 400
    pdf_r = cand.get("/api/candidate/profile.pdf")
    assert pdf_r.status_code == 200 and pdf_r.content[:4] == b"%PDF"


def test_fsp_link_and_no_history(client, monkeypatch):
    from app.modules.fsp import router as fsp_router

    data = {
        "FSP-000123": {
            "fsp_id": "FSP-000123",
            "full_name": "Иванова М.С.",
            "region": "Москва",
            "sport_rank": "КМС",
            "achievements": [
                {
                    "id": "a1",
                    "event": "Всероссийские соревнования по продуктовому программированию",
                    "discipline": "product",
                    "level": "national",
                    "result": "prize",
                    "place": 2,
                    "date": "2026-04-10",
                    "role": "backend",
                }
            ],
        }
    }
    monkeypatch.setattr(fsp_router, "fetch_participant", lambda fid: data.get(fid))
    a = make_candidate(client, "a@example.ru")
    b = make_candidate(client, "b@example.ru")
    pass_test(a)
    pass_test(b)
    r = a.post("/api/fsp/link/demo", json={"fsp_id": "FSP-000123"})
    assert r.status_code == 200 and r.json()["fsp_achievements"][0]["result"] == "prize"
    assert b.post("/api/fsp/link/demo", json={"fsp_id": "FSP-000123"}).status_code == 409
    r = b.post("/api/fsp/link/demo", json={"fsp_id": "FSP-000999"})  # нет в реестре — история пуста
    assert r.status_code == 200 and r.json()["fsp_id"] == "FSP-000999" and r.json()["fsp_achievements"] == []
    emp = make_employer(client)
    s = emp.post(
        "/api/employer/searches",
        json={
            "title": "Backend",
            "text": "Python FastAPI PostgreSQL",
            "specialization": "backend",
            "grade": "middle",
        },
    ).json()
    by_fsp = {x["card"]["fsp_linked"]: x for x in s["results"]}
    fsp_card = next(x for x in s["results"] if x["card"]["fsp"])
    assert any("ФСП: призёр" in r["text"] for r in fsp_card["reasons"])
    other = next(x for x in s["results"] if not x["card"]["fsp"])
    assert any("достижений пока нет" in r["text"] for r in other["reasons"])
    assert by_fsp
    filt = emp.put(
        f"/api/employer/searches/{s['search']['id']}/filters",
        json={"filters": {"has_fsp": True}, "note": "только с ФСП"},
    ).json()
    assert filt["filtered_total"] == 1 and filt["base_total"] == 2 and len(filt["versions"]) == 2
    back = emp.post(f"/api/employer/searches/{s['search']['id']}/revert/1").json()
    assert back["filtered_total"] == 2 and len(back["versions"]) == 3
    # скрытие ФСП в приватности
    a.put("/api/candidate/privacy", json={"show_fsp": False})
    s2 = emp.get(f"/api/employer/searches/{s['search']['id']}").json()
    assert all(not x["card"]["fsp"] for x in s2["results"])


def test_preview_tests_from_vacancy(client):
    text = (
        "Python-разработчик (Middle). Требования: Python, FastAPI, PostgreSQL, Docker, понимание HTTP и REST."
    )
    r = client.post(
        "/api/assessment/preview",
        json={"text": text, "title": "Python-разработчик (Middle)", "candidates": 2, "items": 8},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["specialization"] == "backend" and d["grade"] == "middle"
    assert len(d["tests"]) == 2 and all(len(t["items"]) == 8 for t in d["tests"])
    # концептуальные вопросы с выбором имеют небольшое число формулировок — редкие совпадения допустимы
    assert d["shared_instances"] <= 2
    assert abs(d["tests"][0]["mean_b"] - d["tests"][1]["mean_b"]) < 1.0


def test_specialization_change_resets_category(client):
    cand = make_candidate(client)
    pass_test(cand)
    r = cand.put("/api/candidate/survey", json={**SURVEY, "specialization": "frontend", "stack": ["React"]})
    assert r.json()["confirmed_grade"] is None and r.json()["category"] is None


def test_test_composition_follows_declared_stack(client):
    """Состав теста — ядро специализации + модули по заявленному стеку; чужой язык не подставляется."""
    java = {**SURVEY, "stack": ["Java", "Spring", "PostgreSQL", "Kafka", "Docker"]}
    cand = make_candidate(client, "java@example.ru", survey=java)
    bp = cand.get("/api/assessment/eligibility").json()["blueprint"]
    assert set(bp["core"]) == {"algorithms", "sql", "http", "architecture"}
    assert "python" not in bp["weights"] and "javascript" not in bp["weights"]
    assert [m["skill"] for m in bp["modules"]] == ["docker"] and "Java" in bp["untested"]
    assert abs(sum(bp["weights"].values()) - 1) < 1e-3 and bp["explanation"]
    att = cand.post("/api/assessment/attempts", json={"grade": "middle"}).json()
    assert all(abs(att["blueprint"][k] - v) < 1e-3 for k, v in bp["weights"].items())
    assert set(att["blueprint"]) == set(bp["weights"])
    assert att["item"]["skill"] in bp["weights"]


def test_relevant_experience_in_search(client):
    """Опыт по местам работы: релевантный (та же специализация) и требование из текста потребности."""
    a = make_candidate(client, "a@example.ru")
    b = make_candidate(client, "b@example.ru")
    jobs_a = [{"title": "Python-разработчик, «Банк»", "start": "2021", "end": None, "industry": "fintech"}]
    jobs_b = [
        {"title": "Менеджер по продажам", "start": "2016", "end": "2024"},
        {"title": "Junior-разработчик", "start": "2025", "end": None, "specialization": "backend"},
    ]
    for api, jobs in ((a, jobs_a), (b, jobs_b)):
        r = api.put("/api/candidate/profile", json={"experience": jobs})
        assert r.status_code == 200, r.text
        pass_test(api, "middle", correct=True)
    bad = a.put("/api/candidate/profile", json={"experience": [{"title": "x", "specialization": "astro"}]})
    assert bad.status_code == 422

    emp = make_employer(client)
    r = emp.post(
        "/api/employer/searches",
        json={
            "title": "Python-разработчик (Middle)",
            "text": "Бэкенд на Python, FastAPI, PostgreSQL, Docker. Опыт коммерческой разработки от 3 лет. Вилка 230-300 тыс ₽, удалённо.",
        },
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["need"]["min_years"] == 3
    res = s["results"]
    assert len(res) == 2
    top, second = res
    assert top["card"]["relevant_years"] >= 5 and top["card"]["industry_years"] == {
        "fintech": top["card"]["relevant_years"]
    }
    assert second["card"]["relevant_years"] < 2 and second["card"]["experience_years"] > 9
    assert any(
        x["text"].startswith("Релевантный опыт") and "требуется от 3 лет" in x["text"] for x in top["reasons"]
    )
    assert "Релевантный опыт: 1,8 года; требуется от 3 лет" in [x["text"] for x in second["reasons"]]
    assert top["score"] > second["score"]
