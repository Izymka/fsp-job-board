"""Семейства заданий (item families) и их экземпляры.

Семейство — это шаблон-генератор: функция `rng -> ItemInstance`, которая рандомизирует
параметры (числа, имена, данные, мутации кода) и *вычисляет* правильный ответ. Все экземпляры
семейства изоморфны по решаемой задаче, поэтому параметры IRT (a, b, c) задаются на уровне
семейства (подход item cloning / automatic item generation).

Правильный ответ существует только на сервере: клиенту отдаётся `ItemInstance.public()`.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .irt import ItemParams

Kind = Literal["single", "multi", "number", "text", "order"]

# Номинальная сложность b по экспертному уровню семейства (1 — базовый … 5 — экспертный).
# Значения согласованы с порогами грейдов в catalog.yaml.
LEVEL_B = {1: -1.75, 2: -0.75, 3: 0.25, 4: 1.15, 5: 2.0}
DEFAULT_A = 1.3


@dataclass
class ItemInstance:
    kind: Kind
    prompt: str
    answer: Any
    code: str | None = None
    code_lang: str | None = None
    options: list[str] | None = None
    tolerance: float = 0.0
    normalize: Literal["exact", "ci", "nospace"] = "ci"
    family_id: str = ""
    explanation: str | None = None

    def public(self) -> dict:
        """Представление для клиента — без правильного ответа."""
        return {
            "kind": self.kind,
            "prompt": self.prompt,
            "code": self.code,
            "code_lang": self.code_lang,
            "options": self.options,
        }

    def check(self, response: Any) -> bool:
        try:
            return _check(self, response)
        except (TypeError, ValueError):
            return False

    def guessing(self) -> float:
        n = len(self.options or [])
        if self.kind == "single":
            return 1.0 / n
        if self.kind == "multi":
            return 1.0 / (2**n - 1)
        if self.kind == "order":
            return 1.0 / math.factorial(n)
        return 0.0


def _norm_text(s: str, mode: str) -> str:
    s = str(s).strip().strip("`").strip()
    if mode == "exact":
        return s
    s = s.casefold().replace("ё", "е")
    if mode == "nospace":
        return re.sub(r"\s+", "", s)
    return re.sub(r"\s+", " ", s)


def _parse_number(x: Any) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    return float(s)


def _check(item: ItemInstance, response: Any) -> bool:
    if response is None:
        return False
    match item.kind:
        case "single":
            return int(response) == int(item.answer)
        case "multi":
            return sorted(int(x) for x in response) == sorted(int(x) for x in item.answer)
        case "order":
            return [int(x) for x in response] == [int(x) for x in item.answer]
        case "number":
            return abs(_parse_number(response) - float(item.answer)) <= item.tolerance + 1e-9
        case "text":
            accepted = item.answer if isinstance(item.answer, (list, tuple)) else [item.answer]
            r = _norm_text(response, item.normalize)
            for a in accepted:
                if r == _norm_text(a, item.normalize):
                    return True
                # «10» и «10.0» — один и тот же числовой ответ
                try:
                    if abs(_parse_number(response) - _parse_number(a)) < 1e-9:
                        return True
                except ValueError:
                    pass
            return False
    return False


# ---------------------------------------------------------------------------------------------
# Конструкторы экземпляров


def single(
    rng: random.Random,
    prompt: str,
    correct: str,
    distractors: Sequence[str],
    *,
    n_options: int = 4,
    code: str | None = None,
    code_lang: str | None = None,
) -> ItemInstance:
    """Выбор одного варианта: дистракторы дедуплицируются, порядок перемешивается."""
    pool: list[str] = []
    for d in distractors:
        d = str(d)
        if d != str(correct) and d not in pool:
            pool.append(d)
    rng.shuffle(pool)
    options = [str(correct), *pool[: n_options - 1]]
    if len(options) < 2:
        raise ValueError("недостаточно различных вариантов ответа")
    rng.shuffle(options)
    return ItemInstance(
        kind="single",
        prompt=prompt,
        answer=options.index(str(correct)),
        options=options,
        code=code,
        code_lang=code_lang,
    )


def multi(
    rng: random.Random,
    prompt: str,
    correct: Sequence[str],
    wrong: Sequence[str],
    *,
    n_options: int = 5,
    code: str | None = None,
    code_lang: str | None = None,
) -> ItemInstance:
    correct = list(dict.fromkeys(str(c) for c in correct))
    wrong = [w for w in dict.fromkeys(str(w) for w in wrong) if w not in correct]
    rng.shuffle(wrong)
    options = correct + wrong[: max(0, n_options - len(correct))]
    rng.shuffle(options)
    return ItemInstance(
        kind="multi",
        prompt=prompt + "\n\n*Выберите все верные варианты.*",
        answer=sorted(options.index(c) for c in correct),
        options=options,
        code=code,
        code_lang=code_lang,
    )


def order(rng: random.Random, prompt: str, steps_in_order: Sequence[str]) -> ItemInstance:
    steps = list(steps_in_order)
    shuffled = steps[:]
    while shuffled == steps:
        rng.shuffle(shuffled)
    return ItemInstance(
        kind="order",
        prompt=prompt,
        options=shuffled,
        answer=[shuffled.index(s) for s in steps],
    )


def number(prompt: str, answer: float, *, tolerance: float = 0.0, code=None, code_lang=None):
    return ItemInstance(
        kind="number", prompt=prompt, answer=answer, tolerance=tolerance, code=code, code_lang=code_lang
    )


def text(prompt: str, answer: str | Sequence[str], *, normalize="nospace", code=None, code_lang=None):
    return ItemInstance(
        kind="text", prompt=prompt, answer=answer, normalize=normalize, code=code, code_lang=code_lang
    )


# ---------------------------------------------------------------------------------------------
# Семейства и реестр


@dataclass
class Family:
    id: str
    skill: str
    level: int
    title: str
    generator: Callable[[random.Random], ItemInstance]
    a: float = DEFAULT_A
    b: float | None = None
    time_limit: int | None = None
    # Группа семейств, проверяющих одно и то же разными формулировками (GROUP BY в SQL и groupby
    # в pandas): в одной попытке выдаётся не больше одного семейства группы, между попытками группа
    # считается увиденной целиком.
    group: str | None = None
    _c: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.level not in LEVEL_B:
            raise ValueError(f"{self.id}: level must be 1..5")
        if self.b is None:
            self.b = LEVEL_B[self.level]
        if self.time_limit is None:
            self.time_limit = 60 + 30 * self.level

    @property
    def c(self) -> float:
        if self._c is None:
            self._c = self.generate(0).guessing()
        return self._c

    @property
    def params(self) -> ItemParams:
        return ItemParams(a=self.a, b=float(self.b), c=self.c)

    @property
    def content_key(self) -> str:
        """Единица неповторяемости: группа, если задана, иначе само семейство."""
        return f"group:{self.group}" if self.group else self.id

    def generate(self, seed: int) -> ItemInstance:
        inst = self.generator(random.Random(seed))
        inst.family_id = self.id
        return inst


REGISTRY: dict[str, Family] = {}


def family(id: str, skill: str, level: int, title: str, **kw) -> Callable:
    """Декоратор регистрации семейства в банке."""

    def deco(fn: Callable[[random.Random], ItemInstance]) -> Callable:
        if id in REGISTRY:
            raise ValueError(f"duplicate family id: {id}")
        REGISTRY[id] = Family(id=id, skill=skill, level=level, title=title, generator=fn, **kw)
        return fn

    return deco


def instance_seed(secret: bytes, attempt_id: str, position: int) -> int:
    """Детерминированный seed экземпляра: HMAC(secret, попытка:позиция).

    Позволяет восстановить выданный вариант для апелляции/аудита, не храня текст задания,
    и не даёт клиенту предсказать параметры.
    """
    digest = hmac.new(secret, f"{attempt_id}:{position}".encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")
