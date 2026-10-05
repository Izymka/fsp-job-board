"""Мониторинг утечек: CUSUM по остаткам «факт − ожидание» для каждого семейства.

Если семейство утекло (кандидаты знают решение шаблона), доля верных ответов растёт без роста
способности: остатки x − P(θ̂) систематически положительны. Односторонний CUSUM
S_t = max(0, S_{t−1} + (x_t − p_t) − k) поднимает флаг при S_t > h. Флаг выводит семейство из
ротации до ревизии (новые параметризации / замена шаблона).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CusumConfig:
    k: float = 0.12  # допуск: смещения меньше k на ответ не накапливаются (ARL0 ≈ 4–5 тыс. ответов)
    h: float = 7.0  # порог: выбран по валидации (≈2% ложных тревог на 600 ответов, задержка ~80 ответов)
    min_n: int = 20  # не флагуем семейство по первым ответам


@dataclass
class CusumState:
    s: float = 0.0
    n: int = 0
    flagged_at: int | None = None

    def update(self, expected: float, correct: bool, cfg: CusumConfig = CusumConfig()) -> bool:
        self.n += 1
        self.s = max(0.0, self.s + (float(correct) - expected) - cfg.k)
        if self.flagged_at is None and self.n >= cfg.min_n and self.s > cfg.h:
            self.flagged_at = self.n
        return self.flagged_at is not None


def run_cusum(stream: Iterable[tuple[float, bool]], cfg: CusumConfig = CusumConfig()) -> CusumState:
    st = CusumState()
    for p, x in stream:
        st.update(p, x, cfg)
    return st


def detect(
    streams: dict[str, Sequence[tuple[float, bool]]], cfg: CusumConfig = CusumConfig()
) -> dict[str, int | None]:
    """Номер ответа, на котором семейство помечено как вероятно утёкшее (None — норма)."""
    return {fid: run_cusum(s, cfg).flagged_at for fid, s in streams.items()}
