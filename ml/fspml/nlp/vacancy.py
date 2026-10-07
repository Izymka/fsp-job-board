"""Разбор описания потребности работодателя / вакансии.

Результат: технологии с важностью (обязательные / «будет плюсом»), предполагаемая
специализация и грейд (с вероятностями и объяснением), вилка ЗП и формат, если указаны,
и blueprint теста — доли навыков, которые проверит тест под эту вакансию.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..catalog import get_catalog
from .skills import get_dictionary, norm

PLUS_HEADINGS = re.compile(
    r"(будет плюсом|будет преимуществом|желательно|приветствуется|nice to have|плюсом будет|дополнительно|как плюс)",
    re.I,
)
MUST_HEADINGS = re.compile(
    r"(требования|обязательно|must have|ожидаем|что нужно|необходимо|мы ждем|мы ждём|стек)", re.I
)
DUTY_HEADINGS = re.compile(r"(задачи|обязанности|чем предстоит|что делать|предстоит)", re.I)
OFFER_HEADINGS = re.compile(r"(условия|мы предлагаем|что мы предлагаем|предлагаем|бонусы|о компании)", re.I)

SPEC_TITLE_CUES = {
    "backend": [
        r"back-?end",
        r"бэк-?енд",
        r"бекенд",
        r"серверн",
        r"python[- ]разработчик",
        r"go[- ]разработчик",
        r"java[- ]разработчик",
    ],
    "frontend": [
        r"front-?end",
        r"фронт-?енд",
        r"фронтенд",
        r"верстальщик",
        r"react[- ]разработчик",
        r"веб-интерфейс",
    ],
    "mobile": [r"mobile", r"мобильн", r"android", r"ios", r"flutter"],
    "data_science": [
        r"data scien",
        r"ml[- ]engineer",
        r"машинн\w+ обучени",
        r"дата-?сайент",
        r"ml-инженер",
        r"исследовател\w+ данных",
    ],
    "qa": [r"\bqa\b", r"тестировщ", r"тестировани", r"aqa", r"sdet"],
    "devops": [r"devops", r"sre\b", r"инфраструктур", r"платформенн", r"системн\w+ администратор"],
    "analyst": [r"аналитик", r"analyst", r"бизнес-анализ", r"системн\w+ анализ"],
}

GRADE_CUES = [
    ("lead", [r"\blead\b", r"тимлид", r"техлид", r"руководител", r"head of"]),
    ("senior", [r"senior", r"сеньор", r"старш\w+", r"ведущ\w+"]),  # «ведущий» на рынке ≈ senior
    ("middle", [r"middle", r"мидл"]),
    ("junior", [r"junior", r"джун", r"младш\w+"]),
    ("intern", [r"стаж[её]р", r"intern", r"стажировк", r"практикант"]),
]

EXPERIENCE_RE = re.compile(
    r"(?:опыт\w*[^.\n]{0,40}?)(?:от|не менее|более|больше|минимум|\b)\s*(\d+(?:[.,]\d)?)\s*(?:\+\s*)?(?:год|лет|года|years?)",
    re.I,
)
SALARY_RE = re.compile(
    r"(?:от\s*)?(\d[\d\s]{1,8})\s*(?:(?:до|-|–|—)\s*(\d[\d\s]{1,8}))?\s*(тыс\.?|k|к|000)?\s*(?:₽|руб|р\.|rub)",
    re.I,
)


@dataclass
class ParsedNeed:
    skills: dict[str, float]  # технология → важность 0..1
    must: list[str]
    plus: list[str]
    specialization: str | None
    spec_scores: dict[str, float]
    grade: str | None
    grade_reason: str | None
    min_years: float | None
    salary_from: int | None
    salary_to: int | None
    work_format: str | None
    blueprint: dict[str, float] = field(default_factory=dict)
    explanation: list[str] = field(default_factory=list)


def _classify_heading(h: str) -> str | None:
    if PLUS_HEADINGS.search(h):
        return "plus"
    if DUTY_HEADINGS.search(h):
        return "duty"
    if OFFER_HEADINGS.search(h):
        return "offer"
    if MUST_HEADINGS.search(h):
        return "must"
    return None


# Маркеры внутри строки: «Обязательно: Go, PostgreSQL. Будет плюсом: Kafka», «Kafka будет плюсом»,
# «нужен Go-разработчик, обязательно Go, будет плюсом Kafka». «Дополнительно» здесь не маркер
# («дополнительно оплачиваем обучение»), «не обязательно» — не требование.
INLINE_MARKERS = re.compile(
    r"(?P<plus>будет плюсом|будет преимуществом|желательно|приветствуется|nice to have|плюсом будет|как плюс)"
    r"|(?P<must>(?<!не )\bобязательно|must have|требования|необходимо|мы жд[её]м|что нужно|ожидаем)",
    re.I,
)
SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


def _inline_segments(line: str, base: str) -> list[tuple[str, str]]:
    """Разбить строку на сегменты по встроенным маркерам «обязательно / будет плюсом».

    Предложение с одним маркером целиком получает его тип: так одинаково читаются
    «Будет плюсом: Kafka» и «Опыт с Kafka будет плюсом». Если в предложении маркеры разных
    типов, оно режется по их началу; текст до первого маркера остаётся в текущей секции.
    """
    out: list[tuple[str, str]] = []
    for sent in SENTENCE_END.split(line):
        marks = [(m.start(), m.lastgroup) for m in INLINE_MARKERS.finditer(sent)]
        if not marks:
            out.append((base, sent))
        elif len({k for _, k in marks}) == 1:
            out.append((marks[0][1], sent))
        else:
            out.append((base, sent[: marks[0][0]]))
            for (pos, kind), nxt in zip(marks, [*(p for p, _ in marks[1:]), len(sent)]):
                out.append((kind, sent[pos:nxt]))
    return out


def _sections(text: str) -> list[tuple[str, str]]:
    """Разбить текст на (тип секции, текст) по заголовкам.

    Заголовок — короткая строка («Требования:», «# Задачи», «БУДЕТ ПЛЮСОМ») или начало строки
    до двоеточия («Будет плюсом: Kubernetes, gRPC») — тогда остаток строки относится к новой секции.
    Короткая строка с технологиями («- Знание Go обязательно») — не заголовок, а пункт списка.
    """
    dic = get_dictionary()
    kind = "intro"
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().strip("*#").strip()
        head, sep, rest = stripped.partition(":")
        head, rest = head.strip(), rest.strip()
        if sep and 0 < len(head) <= 40:
            candidate = head
        elif (
            0 < len(stripped) <= 40
            or line.lstrip().startswith("#")
            or (stripped.isupper() and len(stripped) <= 60)
        ):
            candidate, rest = stripped, ""
        else:
            candidate = ""
        new_kind = _classify_heading(candidate) if candidate else None
        if new_kind and dic.extract(candidate, fuzzy=False):
            new_kind = None
        if new_kind:
            if buf:
                out.append((kind, "\n".join(buf)))
            kind, buf = new_kind, []
            # остаток строки после «Обязательно:» может содержать и «Будет плюсом: …»
            if rest and INLINE_MARKERS.search(rest):
                out.extend(seg for seg in _inline_segments(rest, kind) if seg[1].strip())
            elif rest:
                buf = [rest]
            continue
        # Встроенные «обязательно / будет плюсом» внутри строки
        if INLINE_MARKERS.search(line):
            if buf:
                out.append((kind, "\n".join(buf)))
                buf = []
            out.extend(seg for seg in _inline_segments(line, kind) if seg[1].strip())
            continue
        buf.append(line)
    if buf:
        out.append((kind, "\n".join(buf)))
    return out


SECTION_WEIGHT = {"must": 1.0, "intro": 0.85, "duty": 0.8, "plus": 0.45, "offer": 0.2}


def parse_salary(text: str) -> tuple[int | None, int | None]:
    for m in SALARY_RE.finditer(text):
        a = int(re.sub(r"\s", "", m.group(1)))
        b = int(re.sub(r"\s", "", m.group(2))) if m.group(2) else None
        mult = 1000 if (m.group(3) and m.group(3).lower() in ("тыс", "k", "к")) or a < 1000 else 1
        a *= mult
        if b is not None:
            b *= mult if b < 1000 or mult == 1000 else 1
        if 10_000 <= a <= 5_000_000:
            return a, b
    return None, None


def parse_format(text: str) -> str | None:
    t = norm(text)
    if re.search(r"гибрид|hybrid", t):
        return "hybrid"
    if re.search(r"удален|удалён|remote|дистанц", t):
        return "remote"
    if re.search(r"в офисе|офис|on-?site", t):
        return "office"
    return None


def years_ru(y: float) -> str:
    if y != int(y):
        return f"{y:g}".replace(".", ",") + " года"
    n = int(y)
    word = (
        "год"
        if n % 10 == 1 and n % 100 != 11
        else "года"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14
        else "лет"
    )
    return f"{n} {word}"


def detect_grade(title: str, text: str) -> tuple[str | None, str | None, float | None]:
    t_title, t_all = norm(title), norm(title + "\n" + text)
    m = EXPERIENCE_RE.search(t_all)
    years = float(m.group(1).replace(",", ".")) if m else None
    for gid, cues in GRADE_CUES:
        if any(re.search(c, t_title) for c in cues):
            return gid, f"в заголовке указан уровень «{gid.capitalize()}»", years
    if years is not None:
        g = (
            "intern"
            if years < 0.5
            else "junior"
            if years < 2
            else "middle"
            if years < 4
            else "senior"
            if years < 6
            else "lead"
        )
        return g, f"требуемый опыт от {years_ru(years)}", years
    for gid, cues in GRADE_CUES:
        if any(re.search(c, t_all) for c in cues):
            return gid, f"в тексте упоминается уровень «{gid.capitalize()}»", years
    return None, None, None


def parse_need(text: str, title: str = "") -> ParsedNeed:
    dic = get_dictionary()
    cat = get_catalog()
    full = (title + "\n" + text).strip()

    importance: dict[str, float] = {}
    plus: set[str] = set()
    must: set[str] = set()
    for kind, chunk in _sections(full):
        w = SECTION_WEIGHT[kind]
        for name, mention in dic.extract(chunk).items():
            imp = w * (0.85 if mention.fuzzy else 1.0)
            importance[name] = max(importance.get(name, 0.0), imp)
            (plus if kind == "plus" else must).add(name)
    # повторные упоминания чуть повышают важность
    counts = {n: m.count for n, m in dic.extract(full, fuzzy=False).items()}
    for n in importance:
        importance[n] = min(1.0, importance[n] * (1 + 0.1 * (counts.get(n, 1) - 1)))
    must -= {n for n in plus if importance.get(n, 0) < 0.6}
    plus -= must

    # Специализация: индикаторы технологий + сильные сигналы заголовка
    spec_scores = {s: 0.0 for s in cat.specializations}
    for n, imp in importance.items():
        for s, w in dic.techs[n].spec.items():
            if s in spec_scores:
                spec_scores[s] += w * imp
    t_title = norm(title or full.splitlines()[0] if full else "")
    title_hit = None
    for s, cues in SPEC_TITLE_CUES.items():
        if any(re.search(c, t_title) for c in cues):
            spec_scores[s] += 4.0
            title_hit = title_hit or s
    total = sum(math.exp(v) for v in spec_scores.values())
    probs = {s: math.exp(v) / total for s, v in spec_scores.items()}
    spec = max(probs, key=probs.get) if any(v > 0 for v in spec_scores.values()) else None

    grade, grade_reason, years = detect_grade(title, text)
    sal_from, sal_to = parse_salary(full)
    fmt = parse_format(full)

    explanation = []
    if spec:
        top = sorted(
            ((n, importance[n]) for n in importance if dic.techs[n].spec.get(spec, 0) > 0),
            key=lambda x: -x[1],
        )[:4]
        why = "заголовок вакансии" if title_hit == spec else "стек " + ", ".join(n for n, _ in top)
        explanation.append(f"Специализация «{cat.specializations[spec].title}»: {why}")
    if grade:
        explanation.append(f"Грейд {cat.grade(grade).name}: {grade_reason}")

    need = ParsedNeed(
        skills=dict(sorted(importance.items(), key=lambda x: (-x[1], x[0]))),  # детерминированный порядок
        must=sorted(must),
        plus=sorted(plus),
        specialization=spec,
        spec_scores=probs,
        grade=grade,
        grade_reason=grade_reason,
        min_years=years,
        salary_from=sal_from,
        salary_to=sal_to,
        work_format=fmt,
        explanation=explanation,
    )
    need.blueprint = blueprint_from_need(need)
    return need


def blueprint_from_need(need: ParsedNeed, *, base_share: float = 0.4) -> dict[str, float]:
    """Blueprint теста под вакансию.

    Смесь: `base_share` — ядро специализации (сопоставимость с категорией и якоря шкалы),
    остальное — навыки, которые требует вакансия, пропорционально их важности. Язык вакансии
    берётся из её текста: Java-вакансия не получает задания по Python «по умолчанию».
    """
    cat = get_catalog()
    dic = get_dictionary()
    from_vacancy: dict[str, float] = {}
    for name, imp in need.skills.items():
        assess = dic.techs[name].assess
        for s in assess:
            from_vacancy[s] = from_vacancy.get(s, 0.0) + imp / len(assess)
    base = cat.blueprint(need.specialization) if need.specialization else {}
    if not from_vacancy:
        return base
    tot_v = sum(from_vacancy.values())
    share = base_share if base else 0.0
    bp: dict[str, float] = {k: share * v for k, v in base.items()}
    for k, v in from_vacancy.items():
        bp[k] = bp.get(k, 0.0) + (1 - share) * v / tot_v
    # отбрасываем навыки с долей меньше 4% (меньше одного задания в тесте) и нормируем
    bp = {k: v for k, v in bp.items() if v >= 0.04}
    s = sum(bp.values())
    return {k: round(v / s, 4) for k, v in sorted(bp.items(), key=lambda x: -x[1])}
