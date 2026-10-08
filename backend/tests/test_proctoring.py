"""Цифровой проктор: согласия, эталон лица (сверка 1:1 на сервере), правила, кадр для работодателя."""

from __future__ import annotations

import base64
import random
import uuid

from app.core.db import SessionLocal
from app.modules.assessment.models import Attempt
from app.modules.biometrics.models import AttemptSnapshot, BiometricTemplate
from sqlalchemy import select

from tests.conftest import make_candidate, make_employer, pass_test
from tests.test_assessment_v2 import _answer

MODEL = "human-faceres-test"
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 2000).decode()


def face(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0, 0.3) for _ in range(1024)]


def same(v: list[float], seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    return [x + rng.gauss(0, 0.002) for x in v]


def consent(api, kind: str, accepted: bool = True):
    r = api.post("/api/me/consents", json={"kind": kind, "accepted": accepted})
    assert r.status_code == 200, r.text


def start(api, grade: str, emb, snapshot: str | None = None):
    return api.post(
        "/api/assessment/attempts",
        json={
            "grade": grade,
            "proctored": True,
            "embedding": emb,
            "embedding_model": MODEL,
            "snapshot": snapshot,
        },
    )


def run(api, att: dict, *, proctor: dict | None = None, emb=None, correct=True) -> dict:
    while att["status"] == "in_progress":
        extra = {"proctor": proctor or {}}
        if emb is not None and att["item"]["stage"] == "knowledge" and att["item"]["position"] % 3 == 0:
            extra["embedding"] = emb
        att = _answer(api, att, correct=correct, **extra)
    return att


def test_proctored_start_requires_biometric_consent(client):
    cand = make_candidate(client)
    r = start(cand, "junior", face(1))
    assert r.status_code == 409 and r.json()["error"]["code"] == "consent_required"
    # без проктора тест доступен и без согласия на биометрию
    assert cand.post("/api/assessment/attempts", json={"grade": "junior"}).status_code == 201


def test_template_enrolled_encrypted_and_verified(client):
    cand = make_candidate(client)
    consent(cand, "proctoring_biometric")
    me = face(1)
    att = start(cand, "middle", me).json()
    assert att["proctored"] and att["identity"] == "enrolled"
    with SessionLocal() as db:
        t = db.scalars(select(BiometricTemplate)).one()
        assert t.ciphertext and t.enrollments == 1
        raw = b"".join(__import__("struct").pack("<f", x) for x in me[:8])
        assert raw not in t.ciphertext  # хранится шифротекст, а не вектор
        assert db.scalars(select(AttemptSnapshot)).first() is None  # нет согласия на кадр — кадра нет
    att = run(cand, att, emb=same(me), correct=False)
    assert att["status"] == "failed"
    pr = att["result"]["integrity"]["proctoring"]
    assert pr["status"] == "verified" and pr["mismatches"] == 0 and pr["checks"] >= 1
    # следующая попытка — сверка с эталоном
    att2 = start(cand, "junior", same(me, 5)).json()
    assert att2["identity"] == "match"
    att2 = run(cand, att2, emb=same(me, 7))
    assert att2["status"] == "passed" and att2["result"]["integrity"]["level"] == "clean"
    prof_summary = _summary(att2["id"])
    assert prof_summary["proctoring"]["status"] == "verified"


def _summary(attempt_id: str) -> dict:
    from app.modules.candidates.models import CandidateProfile

    with SessionLocal() as db:
        a = db.get(Attempt, uuid.UUID(attempt_id))
        return db.get(CandidateProfile, a.candidate_id).assessment_summary


def test_other_person_flagged_and_voided(client):
    cand = make_candidate(client)
    consent(cand, "proctoring_biometric")
    owner, ringer = face(1), face(2)
    att = run(cand, start(cand, "middle", owner).json(), emb=owner, correct=False)
    # подставной сдающий начинает следующую попытку: на старте — пометка
    att = start(cand, "junior", ringer).json()
    assert att["identity"] == "mismatch"
    # и дважды не совпадает во время теста — попытка аннулируется
    att = run(cand, att, emb=ringer)
    assert att["status"] == "voided"
    assert any("эталон" in x for x in att["result"]["integrity"]["reasons"])


def test_phone_in_frame_and_camera_loss(client):
    cand = make_candidate(client)
    consent(cand, "proctoring_biometric")
    me = face(3)
    att = run(cand, start(cand, "junior", me).json(), proctor={"phone_hits": 2})
    assert att["status"] == "voided" and any("телефон" in x for x in att["result"]["integrity"]["reasons"])
    # камера пропала — не нарушение, но бейдж снимается
    cand2 = make_candidate(client, email="cand2@example.ru")
    consent(cand2, "proctoring_biometric")
    att = run(cand2, start(cand2, "junior", face(4)).json(), proctor={"cam_lost_ms": 10_000})
    assert att["status"] == "passed"
    assert att["result"]["integrity"]["level"] == "clean"
    assert att["result"]["integrity"]["proctoring"]["status"] == "interrupted"


def test_revoking_consent_deletes_template_and_marks_reenrollment(client):
    cand = make_candidate(client)
    consent(cand, "proctoring_biometric")
    run(cand, start(cand, "middle", face(1)).json(), emb=face(1), correct=False)
    consent(cand, "proctoring_biometric", accepted=False)
    with SessionLocal() as db:
        t = db.scalars(select(BiometricTemplate)).one()
        assert t.ciphertext is None and t.deleted_at is not None
    consent(cand, "proctoring_biometric")
    att = start(cand, "junior", face(2)).json()
    assert att["identity"] == "enrolled"
    att = run(cand, att, emb=face(2))
    assert att["status"] == "passed"
    assert _summary(att["id"])["proctoring"]["re_enrolled"] is True


def test_snapshot_visible_only_after_accepted_invitation(client):
    cand = make_candidate(client)
    consent(cand, "proctoring_biometric")
    consent(cand, "proctoring_photo")
    att = run(cand, start(cand, "junior", face(1), snapshot=JPEG).json(), emb=face(1))
    assert att["status"] == "passed"
    cid = str(_candidate_id(att["id"]))
    emp = make_employer(client)
    assert emp.get(f"/api/employer/candidates/{cid}/test-photo").status_code == 403
    assert emp.get(f"/api/employer/candidates/{cid}").json()["test_photo_available"] is False
    inv = emp.post(
        "/api/employer/invitations",
        json={
            "candidate_id": cid,
            "title": "Junior",
            "description": "Команда платформы",
            "salary_from": 100000,
            "salary_to": 150000,
            "contact_method": "email",
            "contact_value": "hr@example.ru",
        },
    ).json()
    assert cand.post(f"/api/candidate/invitations/{inv['id']}/accept").status_code == 200
    card = emp.get(f"/api/employer/candidates/{cid}").json()
    assert card["test_photo_available"] is True
    assert card["assessment"]["proctoring"]["status"] == "verified"
    r = emp.get(f"/api/employer/candidates/{cid}/test-photo")
    assert (
        r.status_code == 200
        and r.headers["content-type"] == "image/jpeg"
        and r.content.startswith(b"\xff\xd8")
    )
    # отзыв согласия на кадр удаляет его
    consent(cand, "proctoring_photo", accepted=False)
    assert emp.get(f"/api/employer/candidates/{cid}/test-photo").status_code == 404


def _candidate_id(attempt_id: str):
    with SessionLocal() as db:
        return db.get(Attempt, uuid.UUID(attempt_id)).candidate_id


def test_regular_test_unchanged(client):
    cand = make_candidate(client)
    att = pass_test(cand, "junior")
    assert att["status"] == "passed"
    assert att["proctored"] is False and att["result"]["integrity"]["proctoring"] is None
