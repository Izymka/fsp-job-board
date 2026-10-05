"""Эмбеддинги текстов для семантической части соответствия «потребность ↔ профиль».

Основной вариант — локальная модель `cointegrated/rubert-tiny2` (sentence-transformers, CPU,
~120 МБ RAM). Если пакет или веса недоступны (оффлайн, тесты), используется char-n-gram TF-IDF с
хешированием — без обучения и скачиваний, устойчив к морфологии и опечаткам.
Никакие тексты не покидают сервер.
"""

from __future__ import annotations

import os
from functools import lru_cache

import numpy as np

MODEL_NAME = os.environ.get("FSP_EMBED_MODEL", "cointegrated/rubert-tiny2")


class HashingEmbedder:
    name = "tfidf-char-ngrams"

    def __init__(self, n_features: int = 2**16) -> None:
        from sklearn.feature_extraction.text import HashingVectorizer

        self._vec = HashingVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            n_features=n_features,
            alternate_sign=False,
            norm="l2",
            lowercase=True,
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        m = self._vec.transform([t or "" for t in texts])
        # сублинейное взвешивание без словаря IDF: log(1+tf), затем L2
        m.data = np.log1p(m.data)
        dense = m.toarray().astype(np.float32)
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        return dense / np.maximum(norms, 1e-9)


class SentenceEmbedder:
    def __init__(self, model_name: str = MODEL_NAME) -> None:
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self._model = SentenceTransformer(model_name, device="cpu")

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            self._model.encode([t or "" for t in texts], normalize_embeddings=True), dtype=np.float32
        )


@lru_cache(maxsize=1)
def get_embedder():
    if os.environ.get("FSP_EMBEDDINGS", "auto") != "hashing":
        try:
            return SentenceEmbedder()
        except Exception:
            pass
    return HashingEmbedder()


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a: (d,) или (n, d); b: (m, d) → косинусная близость (векторы уже нормированы)."""
    return np.clip(np.asarray(b) @ np.asarray(a).T, -1.0, 1.0)
