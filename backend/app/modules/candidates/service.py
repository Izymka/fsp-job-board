"""Сервисный слой профиля кандидата: признаки для подбора, эмбеддинги, карточки, PDF-профиль."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date

import numpy as np
from fspml.catalog import get_catalog
from fspml.matching.experience import ExperienceSummary, summarize
from fspml.matching.scoring import CandidateFeatures, FspAchievement
from fspml.nlp.embed import SentenceEmbedder, get_embedder

from ...core.db import aware
from .models import CandidateProfile


def profile_text(p: CandidateProfile) -> str:
    parts = [p.headline or "", p.about or "", ", ".join(p.stack or [])]
    for job in p.experience or []:
        parts.append(f"{job.get('title', '')} {job.get('description', '')}")
    return "\n".join(x for x in parts if x)


def update_embedding(p: CandidateProfile) -> None:
    """Плотный эмбеддинг храним только для нейросетевой модели; hashing-вектор считаем на лету."""
    emb = get_embedder()
    if isinstance(emb, SentenceEmbedder):
        p.embedding = emb.encode([profile_text(p)])[0].round(5).tolist()
        p.embedding_model = emb.name
    else:
        p.embedding, p.embedding_model = None, None


def embeddings_for(profiles: Sequence[CandidateProfile]) -> list[np.ndarray]:
    emb = get_embedder()
    name = getattr(emb, "name", "")
    out: list[np.ndarray | None] = [None] * len(profiles)
    todo = []
    for i, p in enumerate(profiles):
        if p.embedding is not None and p.embedding_model == name:
            out[i] = np.asarray(p.embedding, dtype=np.float32)
        else:
            todo.append(i)
    if todo:
        vecs = emb.encode([profile_text(profiles[i]) for i in todo])
        for i, v in zip(todo, vecs):
            out[i] = v
    return out  # type: ignore[return-value]


def fsp_achievements(p: CandidateProfile) -> list[FspAchievement] | None:
    if not p.fsp_id:
        return None
    out = []
    for a in p.fsp_achievements or []:
        try:
            out.append(
                FspAchievement(
                    discipline=a["discipline"],
                    level=a["level"],
                    result=a["result"],
                    event_date=date.fromisoformat(a["date"]),
                    title=a.get("title", ""),
                    role=a.get("role"),
                )
            )
        except (KeyError, ValueError):
            continue
    return out


def experience_summary(p: CandidateProfile, today: date | None = None) -> ExperienceSummary | None:
    """Стаж по местам работы профиля; None — мест работы нет (остаётся только заявленный стаж)."""
    s = summarize(list(p.experience or []), p.specialization, today or date.today())
    return s if s.total_years > 0 else None


def features(p: CandidateProfile, embedding: np.ndarray | None = None) -> CandidateFeatures:
    scores = p.skill_scores or {}
    last_active = aware(p.last_active_at)
    confirmed_at = aware(p.confirmed_at)
    return CandidateFeatures(
        id=str(p.user_id),
        specialization=p.specialization or "",
        grade=p.confirmed_grade,
        theta=p.theta,
        theta_se=p.theta_se,
        skill_status={k: v.get("status", "no_data") for k, v in scores.items()},
        skill_theta={k: (v["theta"], v["se"]) for k, v in scores.items() if v.get("theta") is not None},
        claimed=set(p.stack or []),
        task_skills=dict(p.task_skills or {}),
        tasks_score=p.tasks_score or 0.0,
        # скрытые кандидатом достижения не используются и в ранжировании (иначе косвенная утечка)
        fsp=fsp_achievements(p) if p.show_fsp else None,
        salary_from=p.salary_from,
        salary_to=p.salary_to,
        work_formats=set(p.work_formats or []),
        industries=set(p.industries or []),
        excluded_industries=set(p.excluded_industries or []),
        excluded_companies=set(p.excluded_companies or []),
        search_status="closed" if p.hidden else p.search_status,
        last_active=last_active.date() if last_active else None,
        tested_at=confirmed_at.date() if confirmed_at else None,
        about=profile_text(p),
        embedding=embedding,
        proctored=((p.assessment_summary or {}).get("proctoring") or {}).get("status") == "verified",
        integrity=((p.assessment_summary or {}).get("integrity") or {}).get("level") or "ok",
        integrity_severity=((p.assessment_summary or {}).get("integrity") or {}).get("severity"),
        **_experience_kw(p),
    )


def _experience_kw(p: CandidateProfile) -> dict:
    s = experience_summary(p)
    if s is None:
        # заявленный стаж без мест работы; 0 — «нет опыта», явно указанный кандидатом
        return {"experience_years": p.experience_years}
    return {
        "experience_years": max(s.total_years, p.experience_years or 0.0),
        "relevant_years": s.relevant_years,
        "it_years": s.it_years,
        "industry_years": s.industry_years,
    }


def category_label(p: CandidateProfile) -> str | None:
    if not p.specialization or not p.confirmed_grade:
        return None
    cat = get_catalog()
    return f"{cat.specializations[p.specialization].name} · {cat.grade(p.confirmed_grade).name}"


def anonymous_alias(p: CandidateProfile) -> str:
    """Стабильный псевдоним для обезличенной карточки."""
    h = int(hashlib.sha1(str(p.user_id).encode()).hexdigest()[:6], 16) % 9000 + 1000
    spec = get_catalog().specializations.get(p.specialization or "", None)
    return f"{spec.name if spec else 'Кандидат'} #{h}"
