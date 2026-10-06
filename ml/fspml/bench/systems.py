"""Системы ранжирования для бенчмарка: наша механика и сильные бейзлайны.

Все системы получают одно и то же: текст вакансии, её разбор (специализация, грейд — те же
жёсткие фильтры категории) и карточки кандидатов. Отличается только способ упорядочивания
внутри допустимого пула. Так проверяется главное: лучше ли наша механика *общих* нейросетевых
моделей поиска при равной информации.

Бейзлайны:
* `bm25` — Okapi BM25 по карточке;
* `dense_frida` — ai-forever/FRIDA (лидер ruMTEB среди открытых энкодеров);
* `dense_qwen3` — Qwen/Qwen3-Embedding-0.6B (мультиязычный, инструкционный);
* `hybrid_rrf` — слияние BM25 и FRIDA (Reciprocal Rank Fusion, k=60);
* `rerank_bge` — BAAI/bge-reranker-v2-m3 (кросс-энкодер) поверх top-50 гибрида;
* `test_only`, `random` — нижние ориентиры внутри категории.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ..catalog import get_catalog
from ..matching.baselines import BM25
from ..matching.scoring import CandidateFeatures, Need, eligible, rank

DEPTH = 50  # глубина сохраняемых прогонов


@dataclass
class BenchNeed:
    id: str
    source: str  # synthetic | vacancy
    title: str
    text: str  # полный текст, как видит асессор
    need: Need  # разбор текста нашим NLP (общий для всех систем: фильтры категории)
    meta: dict = field(default_factory=dict)


@dataclass
class Corpus:
    feats: list[CandidateFeatures]
    texts: list[str]  # карточки (dossier.render_candidate)

    def __post_init__(self) -> None:
        self.ids = [f.id for f in self.feats]
        self.index = {cid: i for i, cid in enumerate(self.ids)}


Ranker = Callable[[BenchNeed], list[str]]


def eligible_idx(corpus: Corpus, bn: BenchNeed) -> list[int]:
    cat = get_catalog()
    if not bn.need.specialization or not bn.need.grade:
        return []
    return [i for i, f in enumerate(corpus.feats) if eligible(f, bn.need, cat)[0]]


def _order(idx: Sequence[int], scores: np.ndarray, corpus: Corpus) -> list[str]:
    order = sorted(range(len(idx)), key=lambda j: (-scores[j], corpus.ids[idx[j]]))
    return [corpus.ids[idx[j]] for j in order][:DEPTH]


# --------------------------------------------------------------------------------- системы


def ours(corpus: Corpus, today: date, version: int = 1) -> Ranker:
    def run(bn: BenchNeed) -> list[str]:
        if not bn.need.specialization or not bn.need.grade:
            return []
        return [s.candidate_id for s in rank(corpus.feats, bn.need, today, version=version)][:DEPTH]

    return run


def bm25(corpus: Corpus) -> Ranker:
    model = BM25(corpus.texts)

    def run(bn: BenchNeed) -> list[str]:
        idx = eligible_idx(corpus, bn)
        sc = np.asarray(model.scores(bn.text))
        return _order(idx, sc[idx], corpus)

    return run


def random_in_category(corpus: Corpus) -> Ranker:
    def run(bn: BenchNeed) -> list[str]:
        idx = eligible_idx(corpus, bn)
        rng = random.Random(bn.id)
        sc = np.array([rng.random() for _ in idx])
        return _order(idx, sc, corpus)

    return run


def test_only(corpus: Corpus) -> Ranker:
    def run(bn: BenchNeed) -> list[str]:
        idx = eligible_idx(corpus, bn)
        sc = np.array([corpus.feats[i].theta if corpus.feats[i].theta is not None else -9.0 for i in idx])
        return _order(idx, sc, corpus)

    return run


class DenseEncoder:
    """Обёртка sentence-transformers с правильными префиксами запроса/документа для модели."""

    SPECS = {
        "ai-forever/FRIDA": {"query": "search_query: ", "doc": "search_document: "},
        "Qwen/Qwen3-Embedding-0.6B": {
            "query": "Instruct: Given a job vacancy description, retrieve candidate profiles that "
            "best match the vacancy requirements\nQuery:",
            "doc": "",
        },
        "intfloat/multilingual-e5-large": {"query": "query: ", "doc": "passage: "},
    }

    def __init__(self, model_name: str, device: str | None = None) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.name = model_name
        self.model = SentenceTransformer(model_name, device=device)
        self.model.max_seq_length = min(self.model.max_seq_length or 512, 512)
        self.spec = self.SPECS.get(model_name, {"query": "", "doc": ""})

    def encode(self, texts: list[str], kind: str, batch_size: int = 16) -> np.ndarray:
        prefix = self.spec[kind]
        return np.asarray(
            self.model.encode(
                [prefix + t for t in texts],
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )


def dense(corpus: Corpus, encoder: DenseEncoder, needs: Sequence[BenchNeed]) -> Ranker:
    docs = encoder.encode(corpus.texts, "doc")
    queries = dict(zip([n.id for n in needs], encoder.encode([n.text for n in needs], "query")))

    def run(bn: BenchNeed) -> list[str]:
        idx = eligible_idx(corpus, bn)
        sc = docs[idx] @ queries[bn.id]
        return _order(idx, sc, corpus)

    return run


def rrf(corpus: Corpus, *rankers: Ranker, k: int = 60) -> Ranker:
    def run(bn: BenchNeed) -> list[str]:
        idx = eligible_idx(corpus, bn)
        score: dict[str, float] = {corpus.ids[i]: 0.0 for i in idx}
        for r in rankers:
            # прогоны обрезаны до DEPTH; кандидаты вне прогона получают нулевой вклад
            for pos, cid in enumerate(r(bn)):
                score[cid] += 1.0 / (k + pos + 1)
        sc = np.array([score[corpus.ids[i]] for i in idx])
        return _order(idx, sc, corpus)

    return run


class CrossEncoderReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", device: str | None = None) -> None:
        import torch
        from sentence_transformers import CrossEncoder

        device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.name = model_name
        self.model = CrossEncoder(model_name, device=device, max_length=1024)

    def scores(self, query: str, docs: list[str]) -> np.ndarray:
        if not docs:
            return np.zeros(0)
        return np.asarray(
            self.model.predict([(query, d) for d in docs], batch_size=8, show_progress_bar=False)
        )


def rerank(corpus: Corpus, first_stage: Ranker, ce: CrossEncoderReranker, depth: int = DEPTH) -> Ranker:
    def run(bn: BenchNeed) -> list[str]:
        cand = first_stage(bn)[:depth]
        sc = ce.scores(bn.text, [corpus.texts[corpus.index[c]] for c in cand])
        idx = [corpus.index[c] for c in cand]
        return _order(idx, sc, corpus)

    return run
