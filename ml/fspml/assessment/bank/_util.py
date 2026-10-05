"""Вспомогательные функции генераторов: исполнение собственных сниппетов для вычисления ответа.

Исполняется только код, сгенерированный нашими шаблонами (не код кандидата), поэтому
правильный ответ гарантированно совпадает с реальным поведением интерпретатора/СУБД.
"""

from __future__ import annotations

import contextlib
import io
import random
import sqlite3
import textwrap

NAMES = [
    "anna",
    "boris",
    "vera",
    "gleb",
    "dina",
    "egor",
    "zoya",
    "ilya",
    "kira",
    "lev",
    "mila",
    "oleg",
    "rita",
    "sasha",
    "timur",
    "ulyana",
]
WORDS = [
    "alpha",
    "delta",
    "orbit",
    "pixel",
    "radar",
    "sigma",
    "vector",
    "kernel",
    "matrix",
    "socket",
    "cursor",
    "buffer",
]
CITIES = ["Москва", "Казань", "Томск", "Самара", "Пермь", "Омск", "Сочи", "Уфа"]
DEPTS = ["sales", "dev", "ops", "hr", "qa", "data"]


def run_py(code: str) -> str:
    """Исполняет сниппет и возвращает stdout без завершающего перевода строки."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(textwrap.dedent(code), "<item>", "exec"), {"__name__": "__item__"})
    return buf.getvalue().rstrip("\n")


def run_sql(setup: str, query: str) -> list[tuple]:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(setup)
        return con.execute(query).fetchall()
    finally:
        con.close()


def sql_insert(table: str, cols: list[str], rows: list[tuple]) -> str:
    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, str):
            return "'" + v.replace("'", "''") + "'"
        return str(v)

    values = ",\n  ".join("(" + ", ".join(lit(v) for v in r) + ")" for r in rows)
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n  {values};"


def pick(rng: random.Random, seq, k: int | None = None):
    if k is None:
        return rng.choice(list(seq))
    return rng.sample(list(seq), k)


def near_misses(
    rng: random.Random, value: int, spread: int = 3, k: int = 3, lo: int | None = None
) -> list[int]:
    """Числовые дистракторы рядом с правильным ответом (типичные ошибки ±1, ±2)."""
    out: list[int] = []
    deltas = [d for d in range(-spread, spread + 1) if d != 0]
    rng.shuffle(deltas)
    for d in deltas:
        v = value + d
        if (lo is None or v >= lo) and v not in out:
            out.append(v)
        if len(out) >= k:
            break
    return out


def fmt_list(xs) -> str:
    return "[" + ", ".join(repr(x) for x in xs) + "]"
