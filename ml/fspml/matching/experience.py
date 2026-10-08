"""Опыт работы: общий стаж, релевантный (в той же специализации) и отраслевой.

Работодателю важен не стаж вообще, а опыт в той же роли: пять лет поддержки 1С не равны пяти
годам backend-разработки. Должность относится к специализации по явной пометке (кандидат выбрал
в профиле), иначе — по названию должности и стеку в описании.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..nlp.skills import get_dictionary, norm

# Названия должностей → специализация. Порядок важен: «аналитик данных» — DS, а не analyst.
TITLE_HINTS: list[tuple[str, str]] = [
    (
        "data_science",
        r"data scien|ml[- ]?инженер|ml engineer|machine learning|машинн\w* обуч|аналитик данных|"
        r"computer vision|nlp[- ]инженер|исследователь данных|deep learning",
    ),
    (
        "devops",
        r"devops|sre\b|site reliability|инженер инфраструктур|системн\w* администратор|platform engineer",
    ),
    ("qa", r"\bqa\b|тестировщ|тестирован|автотест|quality assurance|sdet"),
    ("mobile", r"android|ios|мобильн|flutter|react native|kotlin[- ]разработ|swift"),
    (
        "frontend",
        r"frontend|front-end|фронтенд|верстальщик|react[- ]разработ|vue[- ]разработ|веб-разработчик интерфейс",
    ),
    (
        "analyst",
        r"системн\w* аналитик|бизнес[- ]аналитик|аналитик требован|business analyst|system analyst|продуктов\w* аналитик",
    ),
    (
        "backend",
        r"backend|back-end|бэкенд|бекенд|серверн|python[- ]разработ|java[- ]разработ|go[- ]разработ|"
        r"golang|php[- ]разработ|\.net|c#[- ]разработ|node\.?js[- ]разработ|разработчик серверной",
    ),
]

# Доля нерелевантного IT-опыта, которая засчитывается: общая инженерная культура, но не роль.
OTHER_IT_SHARE = 0.3


@dataclass
class ExperienceSummary:
    total_years: float = 0.0
    relevant_years: float = 0.0  # в специализации кандидата
    it_years: float = 0.0
    industry_years: dict[str, float] = field(default_factory=dict)


def job_specialization(title: str, description: str = "") -> str | None:
    """Специализация должности по названию; если по названию не понять — по стеку в описании."""
    t = norm(title or "")
    for spec, rx in TITLE_HINTS:
        if re.search(rx, t):
            return spec
    dic = get_dictionary()
    found = dic.extract(f"{title}\n{description or ''}", fuzzy=False)
    if len(found) < 2:
        return None
    scores: dict[str, float] = {}
    for name in found:
        for s, w in dic.techs[name].spec.items():
            scores[s] = scores.get(s, 0.0) + w
    return max(scores, key=scores.get) if scores else None


def _parse(tok: str | None, *, end: bool, today: date) -> date | None:
    if not tok:
        return today if end else None
    tok = tok.strip().lower()
    if tok in {"по настоящее время", "настоящее время", "сейчас", "present", "now", "н.в."}:
        return today
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", tok) or None
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.fullmatch(r"(\d{1,2})[./](\d{4})", tok)
    if m and 1 <= int(m.group(1)) <= 12:
        return date(int(m.group(2)), int(m.group(1)), 1)
    if re.fullmatch(r"\d{4}", tok):
        return date(int(tok), 12 if end else 1, 1)
    return None


def _merge(iv: list[tuple[date, date]]) -> float:
    """Годы с объединением пересечений (совмещение работ не удваивает стаж)."""
    if not iv:
        return 0.0
    iv = sorted(iv)
    months = 0
    cs, ce = iv[0]
    for s, e in iv[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            months += (ce.year - cs.year) * 12 + ce.month - cs.month + 1
            cs, ce = s, e
    months += (ce.year - cs.year) * 12 + ce.month - cs.month + 1
    return round(months / 12, 1)


def summarize(jobs: list[dict], specialization: str | None, today: date) -> ExperienceSummary:
    """Стаж по списку мест работы профиля: {title, start, end, description, specialization?, industry?}."""
    all_iv, it_iv, rel_iv = [], [], []
    by_ind: dict[str, list[tuple[date, date]]] = {}
    for j in jobs or []:
        s = _parse(j.get("start"), end=False, today=today)
        e = _parse(j.get("end"), end=True, today=today)
        if not s or not e or s > e:
            continue
        iv = (s, min(e, today))
        all_iv.append(iv)
        spec = j.get("specialization") or job_specialization(j.get("title", ""), j.get("description") or "")
        if spec:
            it_iv.append(iv)
            if spec == specialization:
                rel_iv.append(iv)
        if ind := j.get("industry"):
            by_ind.setdefault(ind, []).append(iv)
    return ExperienceSummary(
        total_years=_merge(all_iv),
        relevant_years=_merge(rel_iv),
        it_years=_merge(it_iv),
        industry_years={k: _merge(v) for k, v in by_ind.items()},
    )


def effective_years(relevant: float, it_years: float) -> float:
    """Опыт «в зачёт» требованию вакансии: релевантный целиком, прочий IT — частично."""
    return relevant + OTHER_IT_SHARE * max(0.0, it_years - relevant)


def years_ru(y: float) -> str:
    if y < 1:
        return "меньше года" if y > 0 else "нет"
    n = round(y) if abs(y - round(y)) < 0.05 else None
    if n is None:
        return f"{y:.1f}".replace(".", ",") + " года"
    w = "лет" if 11 <= n % 100 <= 14 else {1: "год", 2: "года", 3: "года", 4: "года"}.get(n % 10, "лет")
    return f"{n} {w}"


def years_from(y: float) -> str:
    """«от …» в родительном падеже: от 1 года, от 3 лет, от 1,5 года, от полугода."""
    if abs(y - 0.5) < 0.05:
        return "от полугода"
    if abs(y - round(y)) >= 0.05:
        return f"от {y:.1f}".replace(".", ",") + " года"
    n = round(y)
    return f"от {n} " + ("года" if n % 10 == 1 and n % 100 != 11 else "лет")
