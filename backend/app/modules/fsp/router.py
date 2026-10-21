"""Привязка ФСП ID (OAuth2/OIDC authorization code) и синхронизация достижений из реестра ФСП.

ФСП ID будет работать на Keycloak; в демо — отдельный realm `fsp-id`. Бэкенд выступает
OIDC-клиентом: при переходе на реальный ФСП ID меняются только issuer/client в конфигурации.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import urllib.parse
import uuid
from datetime import timedelta

import httpx
import jwt
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from fspml.catalog import get_catalog
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.db import SessionLocal, get_db, utcnow
from ...core.errors import AppError, conflict, responses
from ...core.security import require_role
from ..assessment.models import Attempt
from ..assessment.service import notify_fsp_alerts
from ..candidates.models import CandidateProfile
from ..candidates.router import ProfileOut, get_profile, profile_out
from ..employers.fsp_alerts import send_due_digests
from ..users.models import User
from .client import RegistryUnavailable, fetch_participant, fetch_upcoming_events, normalize_achievements

router = APIRouter(prefix="/api/fsp", tags=["ФСП"])
CandidateUser = require_role("candidate")
log = logging.getLogger("fsp")


class LinkStartOut(BaseModel):
    authorize_url: str


def _state(user_id: str, settings: Settings) -> str:
    payload = {
        "uid": user_id,
        "nonce": secrets.token_urlsafe(8),
        "exp": int(time.time()) + 600,
        "purpose": "fsp-link",
    }
    return jwt.encode(payload, settings.assessment_secret, algorithm="HS256")


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.public_api_url}/api/fsp/link/callback"


@router.get(
    "/link/start",
    response_model=LinkStartOut,
    summary="Начать привязку ФСП ID (редирект на страницу входа ФСП ID)",
    responses=responses(401, 403),
)
def link_start(user: User = Depends(CandidateUser), settings: Settings = Depends(get_settings)):
    params = {
        "client_id": settings.fsp_id_client_id,
        "response_type": "code",
        "scope": "openid profile",
        "redirect_uri": _redirect_uri(settings),
        "state": _state(str(user.id), settings),
        "prompt": "login",
    }
    url = (
        f"{settings.keycloak_public_url}/realms/{settings.fsp_id_realm}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(params)
    )
    return LinkStartOut(authorize_url=url)


def link_profile(db: Session, p: CandidateProfile, fsp_id: str) -> None:
    other = db.scalar(
        select(CandidateProfile).where(
            CandidateProfile.fsp_id == fsp_id, CandidateProfile.user_id != p.user_id
        )
    )
    if other is not None:
        raise conflict("fsp_id_taken", "Этот ФСП ID уже привязан к другому профилю")
    p.fsp_id = fsp_id
    p.fsp_linked_at = utcnow()
    if sync_profile(p):
        notify_fsp_alerts(db, p)


def sync_profile(p: CandidateProfile) -> bool:
    """Подтянуть достижения. Нет участника в реестре — история ФСП пуста (корректный случай)."""
    try:
        data = fetch_participant(p.fsp_id)
    except RegistryUnavailable as e:
        log.warning("registry unavailable for %s: %s", p.fsp_id, e)
        return False
    # ссылки на проекты команд вводит кандидат — реестр их не знает, при обновлении сохраняем
    projects = {a.get("id"): a.get("project_url") for a in p.fsp_achievements or [] if a.get("project_url")}
    fresh = normalize_achievements(data)
    for a in fresh:
        if a.get("id") in projects:
            a["project_url"] = projects[a["id"]]
    p.fsp_achievements = fresh
    p.fsp_profile = {k: data.get(k) for k in ("full_name", "region", "sport_rank")} if data else None
    p.fsp_synced_at = utcnow()
    return True


@router.get(
    "/link/callback",
    include_in_schema=True,
    summary="Callback ФСП ID (браузерный редирект)",
    response_class=RedirectResponse,
    status_code=302,
)
def link_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    back = f"{settings.frontend_url}/candidate/settings"
    if error or not code or not state:
        return RedirectResponse(f"{back}?fsp=cancelled")
    try:
        st = jwt.decode(state, settings.assessment_secret, algorithms=["HS256"])
        if st.get("purpose") != "fsp-link":
            raise jwt.InvalidTokenError("purpose")
        user_id = uuid.UUID(st["uid"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return RedirectResponse(f"{back}?fsp=invalid_state")
    token_url = (
        f"{settings.keycloak_internal_url}/realms/{settings.fsp_id_realm}/protocol/openid-connect/token"
    )
    try:
        r = httpx.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(settings),
                "client_id": settings.fsp_id_client_id,
                "client_secret": settings.fsp_id_client_secret,
            },
            timeout=10,
        )
        r.raise_for_status()
        # id_token получен напрямую с token endpoint по серверному каналу → подпись можно не проверять повторно
        claims = jwt.decode(r.json()["id_token"], options={"verify_signature": False})
    except Exception as e:  # noqa: BLE001
        log.warning("fsp token exchange failed: %s", e)
        return RedirectResponse(f"{back}?fsp=error")
    # только выделенный claim ФСП ID: preferred_username задаёт пользователь IdP, а не реестр
    raw_id = claims.get("fsp_id")
    fsp_id = str(raw_id).upper() if raw_id else None  # Keycloak хранит логины в нижнем регистре
    user = db.get(User, user_id)
    if user is None or user.role != "candidate" or not fsp_id:
        return RedirectResponse(f"{back}?fsp=error")
    p = get_profile(db, user)
    try:
        link_profile(db, p, fsp_id)
    except AppError as e:
        return RedirectResponse(f"{back}?fsp={e.code}")
    db.commit()
    return RedirectResponse(f"{back}?fsp=linked")


class DemoLinkIn(BaseModel):
    fsp_id: str = Field(pattern=r"^FSP-\d{6}$")


@router.post(
    "/link/demo",
    response_model=ProfileOut,
    summary="Демо-привязка без ФСП ID (только AUTH_MODE=dev)",
    include_in_schema=False,
)
def link_demo(
    body: DemoLinkIn,
    user: User = Depends(CandidateUser),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if settings.auth_mode != "dev":
        raise AppError(404, "not_found", "Not found")
    p = get_profile(db, user)
    link_profile(db, p, body.fsp_id)
    db.commit()
    return profile_out(p)


@router.post(
    "/sync",
    response_model=ProfileOut,
    summary="Обновить достижения из реестра ФСП",
    responses=responses(401, 403, 409, 503),
)
def sync(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    if not p.fsp_id:
        raise conflict("fsp_not_linked", "ФСП ID не привязан")
    if not sync_profile(p):
        raise AppError(503, "registry_unavailable", "Реестр ФСП временно недоступен, попробуйте позже")
    notify_fsp_alerts(db, p)
    db.commit()
    return profile_out(p)


class GrowthEvent(BaseModel):
    id: str
    title: str
    discipline: str
    level: str
    start_date: str
    city: str | None = None
    relevance: float


class GrowthOut(BaseModel):
    weak_skills: list[str] = Field(description="навыки теста со статусом «слабо» или «неуверенно»")
    events: list[GrowthEvent] = Field(description="ближайшие соревнования ФСП, релевантные специализации")
    registry_available: bool = True


@router.get(
    "/growth",
    response_model=GrowthOut,
    summary="План роста: что подтянуть по итогам теста и ближайшие соревнования ФСП",
    responses=responses(401, 403),
)
def growth(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    """Соревнования ФСП — способ получить подтверждённое реестром достижение, которое платформа
    засчитывает как опыт (подбор v7) и как приор теста. Дисциплины ранжируются по релевантности
    специализации кандидата (матрица `catalog.yaml`), ниже 0.5 — не предлагаются."""
    p = get_profile(db, user)
    # подоценки последней завершённой попытки (в профиль они попадают только при подтверждении)
    last = db.scalar(
        select(Attempt)
        .where(
            Attempt.candidate_id == p.user_id, Attempt.finished_at.is_not(None), Attempt.result.is_not(None)
        )
        .order_by(Attempt.finished_at.desc())
        .limit(1)
    )
    skills = ((last.result or {}).get("skills") if last else None) or p.skill_scores or {}
    order = {"weak": 0, "uncertain": 1}
    weak = sorted(
        (k for k, v in skills.items() if v.get("status") in order),
        key=lambda k: (order[skills[k]["status"]], k),
    )
    cat = get_catalog()
    try:
        events = fetch_upcoming_events()
        available = True
    except RegistryUnavailable:
        events, available = [], False
    spec = p.specialization or ""
    rows = []
    for e in events:
        rel = cat.fsp_relevance(e["discipline"], spec) if spec else 0.0
        if rel >= 0.5:
            rows.append(
                GrowthEvent(
                    id=e["id"],
                    title=e["title"],
                    discipline=e["discipline"],
                    level=e["level"],
                    start_date=str(e["start_date"]),
                    city=e.get("city"),
                    relevance=rel,
                )
            )
    rows.sort(key=lambda e: (-e.relevance, e.start_date))
    return GrowthOut(
        weak_skills=weak[:6],
        events=sorted(rows[:5], key=lambda e: e.start_date),
        registry_available=available,
    )


class ProjectIn(BaseModel):
    url: str | None = Field(
        default=None,
        max_length=500,
        pattern=r"^https://\S+$",
        description="Ссылка на проект команды (репозиторий, демо); null — убрать",
    )


@router.put(
    "/achievements/{achievement_id}/project",
    response_model=ProfileOut,
    summary="Ссылка на проект команды для достижения ФСП (видна работодателю в карточке)",
    responses=responses(401, 403, 404, 422),
)
def set_project(
    achievement_id: str, body: ProjectIn, user: User = Depends(CandidateUser), db: Session = Depends(get_db)
):
    p = get_profile(db, user)
    items = [dict(a) for a in p.fsp_achievements or []]
    hit = next((a for a in items if a.get("id") == achievement_id), None)
    if hit is None:
        raise AppError(404, "not_found", "Достижение не найдено")
    if body.url:
        hit["project_url"] = body.url
    else:
        hit.pop("project_url", None)
    p.fsp_achievements = items  # новый список — SQLAlchemy видит изменение JSON
    db.commit()
    return profile_out(p)


@router.delete("/link", response_model=ProfileOut, summary="Отвязать ФСП ID", responses=responses(401, 403))
def unlink(user: User = Depends(CandidateUser), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    p.fsp_id = None
    p.fsp_linked_at = p.fsp_synced_at = None
    p.fsp_achievements = []
    p.fsp_profile = None
    db.commit()
    return profile_out(p)


FspAdmin = require_role("fsp_admin")
FUNNEL_STAGES = (
    ("registered", "Зарегистрировались"),
    ("survey", "Заполнили опрос"),
    ("confirmed", "Подтвердили грейд"),
    ("contacted", "Получили приглашение или откликнулись"),
    ("accepted", "Договорились о контакте"),
    ("hired", "Вышли на работу"),
)
MIN_CELL = 5  # меньшие группы не показываются: по редкому сочетанию (регион × дисциплина) узнаётся человек


class FunnelRow(BaseModel):
    key: str
    title: str
    counts: dict[str, int | None] = Field(description="этап → число участников; null — группа меньше порога")


class FunnelOut(BaseModel):
    stages: list[dict[str, str]]
    fsp: FunnelRow
    baseline: FunnelRow = Field(description="кандидаты без ФСП ID — для сравнения конверсии")
    by_level: list[FunnelRow]
    by_discipline: list[FunnelRow]
    by_specialization: list[FunnelRow]
    by_region: list[FunnelRow]
    min_cell: int = MIN_CELL


def _stages(db: Session) -> dict:
    """Этапы, пройденные каждым кандидатом: только факты, без персональных данных."""
    from ..invitations.models import ACCEPTED_STATUSES, Invitation
    from ..vacancies.models import Application

    inv = db.execute(select(Invitation.candidate_id, Invitation.status)).all()
    apps = db.execute(select(Application.candidate_id, Application.status)).all()
    contacted, accepted, hired = set(), set(), set()
    for cid, st in inv:
        contacted.add(cid)
        if st in ACCEPTED_STATUSES:
            accepted.add(cid)
        if st == "hired":
            hired.add(cid)
    for cid, st in apps:
        contacted.add(cid)
        if st in ("interview", "hired"):
            accepted.add(cid)
        if st == "hired":
            hired.add(cid)
    return {"contacted": contacted, "accepted": accepted, "hired": hired}


def _passed(p: CandidateProfile, facts: dict) -> set[str]:
    out = {"registered"}
    if p.survey_completed_at:
        out.add("survey")
    if p.confirmed_grade:
        out.add("confirmed")
    for k in ("contacted", "accepted", "hired"):
        if p.user_id in facts[k]:
            out.add(k)
    return out


def _row(key: str, title: str, passed: list[set[str]]) -> FunnelRow:
    counts: dict[str, int | None] = {}
    for st, _ in FUNNEL_STAGES:
        n = sum(1 for x in passed if st in x)
        counts[st] = n if n >= MIN_CELL or n == 0 else None
    return FunnelRow(key=key, title=title, counts=counts)


@router.get(
    "/funnel",
    response_model=FunnelOut,
    summary="Воронка трудоустройства участников ФСП (только агрегаты, для федерации)",
    responses=responses(401, 403),
)
def funnel(user: User = Depends(FspAdmin), db: Session = Depends(get_db)):
    """Сколько участников ФСП с привязанным ФСП ID прошли каждый этап — от регистрации до выхода на
    работу, в сравнении с кандидатами без ФСП. Кандидаты, скрывшие ФСП, в разрезах ФСП не участвуют.
    Группы меньше MIN_CELL человек не раскрываются."""
    cat = get_catalog()
    facts = _stages(db)
    profiles = db.scalars(select(CandidateProfile)).all()
    fsp = [p for p in profiles if p.fsp_id and p.show_fsp]
    base = [p for p in profiles if not p.fsp_id]
    lvl_w = {x["id"]: x["weight"] for x in cat.fsp["levels"]}
    lvl_t = {x["id"]: x["title"] for x in cat.fsp["levels"]}
    disc_t = {x["id"]: x["title"] for x in cat.fsp["disciplines"]}

    def best(p):
        ach = p.fsp_achievements or []
        return max(ach, key=lambda a: lvl_w.get(a.get("level"), 0), default=None)

    def group(key_fn, titles: dict[str, str]) -> list[FunnelRow]:
        buckets: dict[str, list[set[str]]] = {}
        for p in fsp:
            buckets.setdefault(key_fn(p), []).append(_passed(p, facts))
        rows = [_row(k, titles.get(k, k), v) for k, v in buckets.items()]
        return sorted(rows, key=lambda r: -(r.counts["registered"] or 0))

    none_t = {"none": "Без достижений в реестре"}
    return FunnelOut(
        stages=[{"id": k, "title": t} for k, t in FUNNEL_STAGES],
        fsp=_row("fsp", "Участники ФСП", [_passed(p, facts) for p in fsp]),
        baseline=_row("baseline", "Кандидаты без ФСП ID", [_passed(p, facts) for p in base]),
        by_level=group(lambda p: (best(p) or {}).get("level") or "none", {**lvl_t, **none_t}),
        by_discipline=group(lambda p: (best(p) or {}).get("discipline") or "none", {**disc_t, **none_t}),
        by_specialization=group(
            lambda p: p.specialization or "none",
            {**{k: v.title for k, v in cat.specializations.items()}, "none": "Не выбрана"},
        ),
        by_region=group(lambda p: (p.fsp_profile or {}).get("region") or "none", {"none": "Не указан"}),
    )


def sync_loop(stop: threading.Event) -> None:
    """Фоновая синхронизация привязанных профилей с реестром (по расписанию)."""
    s = get_settings()
    while not stop.wait(60):
        try:
            with SessionLocal() as db:
                cutoff = utcnow() - timedelta(hours=s.fsp_sync_interval_hours)
                rows = db.scalars(
                    select(CandidateProfile)
                    .where(
                        CandidateProfile.fsp_id.is_not(None),
                        or_(
                            CandidateProfile.fsp_synced_at.is_(None), CandidateProfile.fsp_synced_at < cutoff
                        ),
                    )
                    .limit(50)
                ).all()
                for p in rows:
                    if (p.fsp_synced_at is None or p.fsp_synced_at < cutoff) and sync_profile(p):
                        notify_fsp_alerts(db, p)
                send_due_digests(db)
                db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("fsp sync loop error: %s", e)
