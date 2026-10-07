"""Гибрид «структура + семантика»: формула подбора + кросс-энкодер.

* Первый этап — формула (по умолчанию v5): жёсткие фильтры категории, подтверждённые тестом
  навыки с весом по специфичности требования, сила профиля, «ворота» по обязательному стеку,
  формату и вилке. Она знает «правила игры» рынка.
* Второй этап — кросс-энкодер BAAI/bge-reranker-v2-m3 читает вместе текст вакансии и карточку
  кандидата (с текстом резюме) и оценивает смысловое соответствие — то, чего не видит словарь.
* Порядки объединяются методом Reciprocal Rank Fusion: балл кандидата = w / (k + место у формулы) +
  1 / (k + место у кросс-энкодера), k = 60, w = 2 (голос формулы вдвое весомее).

RRF смешивает *места*, а не баллы, поэтому не требует согласовывать шкалы двух моделей.
На реалистичном бенчмарке (docs/bench.md, bench2) по слепому судье: v1 0.704 → гибрид на v1
(«v4») 0.736 → v5 0.810 → гибрид на v5 0.836.

Модель исполняется локально (без облака и передачи ПДн). Если пакет или веса недоступны,
работает одна формула.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from datetime import date
from functools import lru_cache

from .scoring import CandidateFeatures, Need, Reason, Scored, rank

RERANKER_MODEL = os.environ.get("FSP_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
DEPTH = 50  # сколько лидеров v1 переупорядочивает кросс-энкодер
RRF_K = 60
W_STRUCT = 2.0


@lru_cache(maxsize=1)
def get_reranker():
    """Кросс-энкодер или None (нет пакета/весов, FSP_RERANKER=off)."""
    if os.environ.get("FSP_RERANKER", "on") == "off":
        return None
    try:
        import torch
        from sentence_transformers import CrossEncoder

        device = (
            "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        )
        return CrossEncoder(RERANKER_MODEL, device=device, max_length=1024)
    except Exception:
        return None


def fuse(struct_order: list[str], sem_order: list[str], *, k: int = RRF_K, w: float = W_STRUCT) -> list[str]:
    score: dict[str, float] = {}
    for i, cid in enumerate(struct_order):
        score[cid] = score.get(cid, 0.0) + w / (k + i + 1)
    for i, cid in enumerate(sem_order):
        score[cid] = score.get(cid, 0.0) + 1.0 / (k + i + 1)
    return sorted(score, key=lambda c: (-score[c], c))


def rank_hybrid(
    candidates: Iterable[CandidateFeatures],
    need: Need,
    today: date,
    *,
    card_text: Callable[[CandidateFeatures], str],
    reranker=None,
    depth: int = DEPTH,
    version: int = 5,
) -> list[Scored]:
    """card_text — текст карточки кандидата, как его видит работодатель; version — версия формулы."""
    feats = list(candidates)
    base = rank(feats, need, today, version=version)
    reranker = reranker if reranker is not None else get_reranker()
    if reranker is None or not base or not need.text:
        return base
    head, tail = base[:depth], base[depth:]
    by_id = {f.id: f for f in feats}
    pairs = [(need.text, card_text(by_id[s.candidate_id])) for s in head]
    sem = list(reranker.predict(pairs, batch_size=8, show_progress_bar=False))
    sem_order = [s.candidate_id for _, s in sorted(zip(sem, head), key=lambda t: (-t[0], t[1].candidate_id))]
    sem_place = {cid: i for i, cid in enumerate(sem_order)}
    scored = {s.candidate_id: s for s in head}
    out = []
    third = max(1, len(head) // 3)
    for cid in fuse([s.candidate_id for s in head], sem_order):
        s = scored[cid]
        place = sem_place[cid]
        if place < third:
            s.reasons.append(Reason("positive", "Резюме по смыслу близко к описанию вакансии"))
        elif place >= len(head) - third:
            s.reasons.append(Reason("neutral", "Резюме по смыслу слабо перекликается с вакансией"))
        s.details["semantic_place"] = place + 1
        out.append(s)
    return out + tail
