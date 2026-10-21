"""Подбор для работодателя: признаки кандидатов из БД → ранжирование fspml → обезличенные карточки."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import date

import numpy as np
from fspml.catalog import get_catalog
from fspml.matching.scoring import (
    Need,
    Scored,
    fsp_strength,
    profile_strength,
    rank,
    recommend_categories,
    salary_fit,
    weights_for,
)
from fspml.nlp.embed import get_embedder
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import aware, utcnow
from ..candidates.models import CandidateProfile
from ..candidates.service import (
    anonymous_alias,
    category_label,
    embeddings_for,
    experience_summary,
    features,
    revealed_contacts,
)
from ..invitations.access import revealed_set
from .models import Company, Search


class ReasonOut(BaseModel):
    kind: str
    text: str


class FspItem(BaseModel):
    id: str | None = None
    title: str
    discipline: str
    level: str
    result: str
    date: str
    place: int | None = None
    role: str | None = None
    team: str | None = None
    project_url: str | None = None


class CandidateCard(BaseModel):
    """Карточка кандидата для работодателя. До контакта — без ФИО и контактов."""

    id: str
    alias: str
    revealed: bool
    full_name: str | None = None
    contacts: dict | None = None
    category: str | None
    specialization: str | None
    grade: str | None
    confirmed_at: str | None
    city: str | None
    headline: str | None
    about: str | None
    experience_years: float | None
    relevant_years: float | None = None  # опыт в специализации (по местам работы)
    it_years: float | None = None
    industry_years: dict[str, float] = {}
    stack: list[str]
    confirmed_skills: list[str]
    skill_scores: dict[str, str]
    test_percentile: float | None
    work_formats: list[str]
    search_status: str
    last_active_days: int | None
    fsp_linked: bool
    fsp_visible: bool
    # сам ФСП ID — только после согласия кандидата (принятое приглашение или отклик): по нему
    # в реестре находится ФИО, до согласия работодатель видит лишь факт привязки и достижения
    fsp_id: str | None = None
    fsp_strength: float
    fsp: list[FspItem]
    profile_strength: float
    salary_fit: str | None = None
    # надёжность прохождения теста, проктор и практический кейс (Middle+):
    # {integrity: {level, reasons}, proctoring: {status, identity, re_enrolled, ...} | None, scenario}
    assessment: dict | None = None
    test_photo_available: bool = False  # кадр с теста с проктором (после принятого приглашения/отклика)


class RankedCandidate(BaseModel):
    card: CandidateCard
    score: float
    components: dict[str, float]
    reasons: list[ReasonOut]
    missing: list[str]
    adjacent: bool
    salary_fit: str
    shortlisted: bool = False


def webhook_signing_key(company_id) -> str:
    """Ключ подписи вебхуков компании: производный от секрета платформы, хранить отдельно не нужно."""
    return hmac.new(
        get_settings().webhook_secret.encode(), str(company_id).encode(), hashlib.sha256
    ).hexdigest()


# FSP_RANKER → версия формулы `rank`; гибриды (hybrid, v4) — кросс-энкодер поверх v5 / v1
FORMULA_VERSIONS = {"v1": 1, "v4": 1, "v5": 5, "hybrid": 5, "v6": 6, "v7": 7}


def formula_version(ranker: str | None = None) -> int:
    return FORMULA_VERSIONS.get(ranker or get_settings().fsp_ranker, 7)


def excluded_for(p: CandidateProfile, company: Company) -> bool:
    """Кандидат скрыл себя от этой компании или от её отрасли (настройки приватности).

    Отрасль берётся у компании, а не у подборки: подборка с другой отраслью не должна открывать
    кандидата, скрывшегося от отрасли работодателя."""
    if str(company.id) in (p.excluded_companies or []):
        return True
    return bool(company.industry and company.industry in (p.excluded_industries or []))


def visible_profiles(
    db: Session, spec: str | None = None, grades: list[str] | None = None
) -> list[CandidateProfile]:
    q = select(CandidateProfile).where(
        CandidateProfile.confirmed_grade.is_not(None), CandidateProfile.hidden.is_(False)
    )
    if spec:
        q = q.where(CandidateProfile.specialization == spec)
    if grades:
        q = q.where(CandidateProfile.confirmed_grade.in_(grades))
    return list(db.scalars(q).all())


def _percentiles(profiles: list[CandidateProfile]) -> dict[uuid.UUID, float]:
    groups: dict[tuple, list[float]] = {}
    for p in profiles:
        if p.theta is not None:
            groups.setdefault((p.specialization, p.confirmed_grade), []).append(p.theta)
    for k in groups:
        groups[k].sort()
    out = {}
    for p in profiles:
        g = groups.get((p.specialization, p.confirmed_grade))
        if p.theta is not None and g and len(g) >= 5:
            out[p.user_id] = float(np.searchsorted(g, p.theta, side="right")) / len(g)
    return out


def _experience_card(p: CandidateProfile) -> dict:
    s = experience_summary(p)
    if s is None:
        return {}
    return {
        "experience_years": max(s.total_years, p.experience_years or 0.0),
        "relevant_years": s.relevant_years,
        "it_years": s.it_years,
        "industry_years": s.industry_years,
    }


def card(
    p: CandidateProfile,
    *,
    revealed: bool,
    percentile: float | None = None,
    today: date | None = None,
    offer: tuple[int | None, int | None] | None = None,
) -> CandidateCard:
    cat = get_catalog()
    today = today or utcnow().date()
    f = features(p)
    la = aware(p.last_active_at)
    fsp_items = []
    if p.fsp_id and p.show_fsp:
        for a in sorted(p.fsp_achievements or [], key=lambda a: a.get("date", ""), reverse=True):
            fsp_items.append(
                FspItem(
                    id=a.get("id"),
                    title=a.get("title", ""),
                    discipline=a.get("discipline", ""),
                    level=a.get("level", ""),
                    result=a.get("result", ""),
                    date=a.get("date", ""),
                    place=a.get("place"),
                    role=a.get("role"),
                    team=a.get("team"),
                    project_url=a.get("project_url"),
                )
            )
    full_name, contacts = revealed_contacts(p) if revealed else (None, None)
    sal = salary_fit(f, *offer)[1] if offer else None
    return CandidateCard(
        id=str(p.user_id),
        alias=anonymous_alias(p),
        revealed=revealed,
        full_name=full_name,
        contacts=contacts,
        category=category_label(p),
        specialization=p.specialization,
        grade=p.confirmed_grade,
        confirmed_at=p.confirmed_at.date().isoformat() if p.confirmed_at else None,
        city=p.city,
        headline=p.headline,
        about=p.about,
        **{"experience_years": p.experience_years, **_experience_card(p)},
        stack=list(p.stack or []),
        confirmed_skills=[
            cat.assessment_skills.get(k, {}).get("title", k)
            for k, v in (p.skill_scores or {}).items()
            if v.get("status") == "confirmed"
        ],
        skill_scores={k: v.get("status", "no_data") for k, v in (p.skill_scores or {}).items()},
        test_percentile=percentile,
        work_formats=list(p.work_formats or []),
        search_status=p.search_status,
        last_active_days=(today - la.date()).days if la else None,
        fsp_linked=bool(p.fsp_id),
        fsp_visible=bool(p.fsp_id and p.show_fsp),
        fsp_id=p.fsp_id if (revealed and p.show_fsp) else None,
        fsp_strength=round(fsp_strength(f.fsp, p.specialization or "", today), 3),
        fsp=fsp_items,
        profile_strength=round(profile_strength(f, today, weights_for(formula_version()))[0], 3),
        salary_fit=sal,
        assessment=p.assessment_summary,
    )


def need_of(s: Search) -> Need:
    return Need(
        specialization=s.specialization,
        grade=s.grade,
        skills=dict(s.skills or {}),
        salary_from=s.salary_from,
        salary_to=s.salary_to,
        work_format=s.work_format,
        industry=s.industry,
        min_years=s.min_years,
        fsp_friendly=bool(s.fsp_friendly),
        text="\n".join(x for x in (s.title, s.team_description or "", s.text or "") if x),
        include_adjacent=s.include_adjacent and not (s.filters or {}).get("exclude_adjacent", False),
    )


def apply_filters(scored: list[Scored], profiles: dict[str, CandidateProfile], filters: dict) -> list[Scored]:
    """Фильтры уточнения поверх базовой подборки (сама подборка не пересчитывается и не теряется)."""
    if not filters:
        return scored
    out = []
    for s in scored:
        p = profiles[s.candidate_id]
        if filters.get("grades") and p.confirmed_grade not in filters["grades"]:
            continue
        if filters.get("skills") and not set(filters["skills"]) <= set(p.stack or []):
            continue
        if filters.get("confirmed_skills"):
            st = p.skill_scores or {}
            if not all(st.get(k, {}).get("status") == "confirmed" for k in filters["confirmed_skills"]):
                continue
        if filters.get("has_fsp") is True and not (p.fsp_id and p.show_fsp and p.fsp_achievements):
            continue
        if filters.get("formats") and not set(filters["formats"]) & set(p.work_formats or []):
            continue
        if filters.get("salary_fit_only") and s.salary_fit == "below":
            continue
        if filters.get("only_active") and p.search_status != "active":
            continue
        if filters.get("min_score") and s.score < float(filters["min_score"]):
            continue
        if filters.get("cities") and p.city not in filters["cities"]:
            continue
        out.append(s)
    return out


def run_search(db: Session, company: Company, s: Search, *, limit: int = 50) -> dict:
    cat = get_catalog()
    need = need_of(s)
    g_idx = cat.grade_index(s.grade)
    grades = [g.id for g in cat.grades if abs(g.order - g_idx) <= 1]
    profiles = [p for p in visible_profiles(db, s.specialization, grades) if not excluded_for(p, company)]
    embs = embeddings_for(profiles) if profiles else []
    feats = [features(p, e) for p, e in zip(profiles, embs)]
    if need.text:
        need.embedding = get_embedder().encode([need.text])[0]
    need.company_id = str(company.id)
    if company.industry and not need.industry:
        need.industry = company.industry
    today = utcnow().date()
    by_id = {str(p.user_id): p for p in profiles}
    ranker = get_settings().fsp_ranker
    version = formula_version(ranker)
    if ranker in ("hybrid", "v4"):
        from fspml.bench.dossier import render_candidate
        from fspml.matching.hybrid import rank_hybrid

        pct_ = _percentiles(profiles)
        scored = rank_hybrid(
            feats,
            need,
            today,
            card_text=lambda f: render_candidate(
                f,
                today,
                alias=anonymous_alias(by_id[f.id]),
                percentile=pct_.get(by_id[f.id].user_id),
            ),
            version=version,
        )
    else:
        scored = rank(feats, need, today, version=version)
    base_total = len(scored)
    filtered = apply_filters(scored, by_id, s.filters or {})
    pct = _percentiles(profiles)
    top = filtered[:limit]
    revealed = revealed_set(db, company.id, [by_id[x.candidate_id].user_id for x in top])
    results = []
    for sc in top:
        p = by_id[sc.candidate_id]
        results.append(
            RankedCandidate(
                card=card(p, revealed=p.user_id in revealed, percentile=pct.get(p.user_id), today=today),
                score=sc.score,
                components=sc.components,
                reasons=[ReasonOut(kind=r.kind, text=r.text) for r in sc.reasons],
                missing=sc.missing,
                adjacent=sc.adjacent,
                salary_fit=sc.salary_fit,
            )
        )
    all_feats = [features(p) for p in visible_profiles(db, None, None)]
    spec_scores = (s.parsed or {}).get("spec_scores")
    cats = recommend_categories(all_feats, need, spec_scores)
    return {
        "base_total": base_total,
        "filtered_total": len(filtered),
        "results": results,
        "categories": [
            {
                "specialization": c.specialization,
                "grade": c.grade,
                "label": f"{cat.specializations[c.specialization].name} · {cat.grade(c.grade).name}",
                "total": c.total,
                "with_fsp": c.with_fsp,
                "salary_median": c.salary_median,
                "in_budget_share": c.in_budget_share,
                "relation": c.relation,
            }
            for c in cats
        ],
    }
