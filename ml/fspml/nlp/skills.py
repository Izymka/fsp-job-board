"""Извлечение технологий, софт-скиллов и ролей из текста по словарю с алиасами и нечётким поиском.

Почему словарь, а не NER-модель: в IT-тексте технологии — закрытое множество с устойчивыми
написаниями; словарь прозрачен, мгновенно расширяется и не требует размеченного корпуса,
которого в рамках задачи нет. Опечатки («Postgress», «Kubernets») ловит rapidfuzz.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

import yaml
from rapidfuzz import fuzz, process

from ..catalog import DATA_DIR


@dataclass(frozen=True)
class Tech:
    name: str
    aliases: tuple[str, ...]
    assess: tuple[str, ...]
    spec: dict[str, float]


@dataclass
class Mention:
    name: str
    count: int = 0
    first_pos: int = 10**9
    fuzzy: bool = False


@dataclass
class SkillDictionary:
    techs: dict[str, Tech]
    soft: dict[str, tuple[str, ...]]
    roles: dict[str, tuple[tuple[str, ...], str]]
    _pattern: re.Pattern = field(init=False, repr=False)
    _alias_to_name: dict[str, str] = field(init=False, repr=False)
    _case_sensitive: re.Pattern | None = field(init=False, repr=False)
    _fuzzy_choices: list[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        alias_to_name: dict[str, str] = {}
        short: dict[str, str] = {}
        for t in self.techs.values():
            for a in (t.name, *t.aliases):
                if len(a) <= 2 and a[:1].isupper():
                    short[a] = t.name  # «R», «C», «Go» — только с учётом регистра
                else:
                    alias_to_name[norm(a)] = t.name
        self._alias_to_name = alias_to_name
        parts = sorted(alias_to_name, key=len, reverse=True)
        self._pattern = re.compile(r"(?<![\w+#])(" + "|".join(re.escape(p) for p in parts) + r")(?![\w+#])")
        self._case_sensitive = (
            re.compile(r"(?<![\w+#./-])(" + "|".join(re.escape(s) for s in short) + r")(?![\w+#]|\.\w)")
            if short
            else None
        )
        self._short = short
        self._fuzzy_choices = [a for a in alias_to_name if len(a) >= 6]

    def extract(self, text_: str, *, fuzzy: bool = True) -> dict[str, Mention]:
        found: dict[str, Mention] = {}

        def add(name: str, pos: int, is_fuzzy=False):
            m = found.setdefault(name, Mention(name))
            m.count += 1
            m.first_pos = min(m.first_pos, pos)
            m.fuzzy = m.fuzzy and is_fuzzy if m.count > 1 else is_fuzzy

        t = norm(text_)
        for m in self._pattern.finditer(t):
            add(self._alias_to_name[m.group(1)], m.start())
        if self._case_sensitive is not None:
            for m in self._case_sensitive.finditer(text_):
                add(self._short[m.group(1)], m.start())
        if fuzzy:
            # Опечатки: только длинные токены, которые не совпали точно.
            tokens = set(re.findall(r"[a-zа-я][a-zа-я0-9.+#-]{5,}", t))
            known = set(self._alias_to_name)
            for tok in tokens - known:
                res = process.extractOne(tok, self._fuzzy_choices, scorer=fuzz.ratio, score_cutoff=88)
                if res:
                    name = self._alias_to_name[res[0]]
                    if name not in found:
                        add(name, t.find(tok), is_fuzzy=True)
        return found

    def extract_soft(self, text_: str) -> list[str]:
        t = norm(text_)
        out = []
        for name, aliases in self.soft.items():
            if any(re.search(r"(?<!\w)" + re.escape(norm(a)) + r"(?!\w)", t) for a in (name, *aliases)):
                out.append(name)
        return out

    def extract_roles(self, text_: str) -> list[tuple[str, str]]:
        t = norm(text_)
        out = []
        for name, (aliases, grade) in self.roles.items():
            if any(re.search(r"(?<!\w)" + re.escape(norm(a)) + r"(?!\w)", t) for a in (name, *aliases)):
                out.append((name, grade))
        return out

    def assess_skills(self, names: list[str] | dict) -> Counter:
        """Навыки теста, которые покрывают перечисленные технологии (с кратностью)."""
        c: Counter = Counter()
        for n in names:
            t = self.techs.get(n)
            if t:
                for s in t.assess:
                    c[s] += 1
        return c


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.casefold().replace("ё", "е"))


@lru_cache(maxsize=1)
def get_dictionary() -> SkillDictionary:
    raw = yaml.safe_load((DATA_DIR / "skills.yaml").read_text(encoding="utf-8"))
    techs = {
        row[0]: Tech(name=row[0], aliases=tuple(row[1]), assess=tuple(row[2]), spec=dict(row[3]))
        for row in raw["technologies"]
    }
    soft = {row[0]: tuple(row[1]) for row in raw["soft_skills"]}
    roles = {row[0]: (tuple(row[1]), row[2]) for row in raw["roles"]}
    return SkillDictionary(techs=techs, soft=soft, roles=roles)


@lru_cache(maxsize=1)
def get_skill_graph() -> dict[str, tuple[tuple[str, float], ...]]:
    """Граф частичного зачёта (`data/skill_graph.yaml`): требование → ((чем владеет кандидат, доля), …)."""
    path = DATA_DIR / "skill_graph.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, list[tuple[str, float]]] = {}
    for e in raw.get("edges", []):
        out.setdefault(e["to"], []).append((e["from"], float(e["w"])))
    return {k: tuple(v) for k, v in out.items()}
