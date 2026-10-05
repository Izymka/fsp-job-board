"""Бейзлайны для сравнения в валидации подбора."""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from collections.abc import Sequence


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zа-яё0-9#+.]+", text.lower().replace("ё", "е"))


class BM25:
    """Okapi BM25 по тексту резюме — модель «универсальной площадки» с поиском по ключевым словам."""

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.tokens = [tokenize(d) for d in docs]
        self.k1, self.b = k1, b
        self.avgdl = sum(map(len, self.tokens)) / max(1, len(self.tokens))
        df: Counter = Counter()
        for t in self.tokens:
            df.update(set(t))
        n = len(self.tokens)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.tf = [Counter(t) for t in self.tokens]

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, toks in zip(self.tf, self.tokens):
            dl = len(toks)
            s = 0.0
            for w in q:
                if w in tf:
                    f = tf[w]
                    s += (
                        self.idf.get(w, 0)
                        * f
                        * (self.k1 + 1)
                        / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                    )
            out.append(s)
        return out


def random_order(ids: Sequence[str], seed: int) -> list[str]:
    ids = list(ids)
    random.Random(seed).shuffle(ids)
    return ids
