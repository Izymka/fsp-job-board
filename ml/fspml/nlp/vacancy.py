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
from ..matching.experience import years_from
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

GRADE_ORDER = ("intern", "junior", "middle", "senior", "lead")
GRADE_CUES = [
    ("lead", [r"\blead\b", r"тимлид", r"техлид", r"руководител", r"head of"]),
    ("senior", [r"senior", r"сеньор", r"старш\w+", r"ведущ\w+"]),  # «ведущий» на рынке ≈ senior
    ("middle", [r"middle", r"мидл"]),
    ("junior", [r"junior", r"джун", r"младш\w+"]),
    ("intern", [r"стаж[её]р", r"\bintern\b", r"стажировк", r"практикант"]),
]

# Уровень в тексте (не в заголовке) — только формы, которые описывают самого кандидата: «ищем Junior
# Java Developer», «старшего DevOps-инженера», «на стажировку». Множественное число и творительный падеж
# («со старшими разработчиками», «ведущих конференциях», «техлидом») — про коллег и компанию.
_ROLE = r"(?:\S+[ -]){0,2}?(?:разработчик|программист|инженер|аналитик|тестировщик|специалист|администратор|developer|engineer|analyst|devops|qa|aqa)"
TEXT_LEVEL_CUES = [
    ("lead", r"\b(?:team ?lead|тимлид|техлид)(?:а|у)?\b(?![-–]?(?:ом|ами|ов))"),
    ("senior", r"\bsenior\b\+?|\bсеньор(?:а|у)?\b|\b(?:старш|ведущ)(?:ий|его|ему|ая|ую)\s+" + _ROLE),
    ("middle", r"\bmiddle\b\+?|\bмидл(?:а|у)?\b"),
    ("junior", r"\bjunior\b\+?|\bджун(?:а|у)?\b|\bмладш(?:ий|его|ему|ая|ую)\s+" + _ROLE),
    ("intern", r"\bintern\b|\bстаж[её]р(?:а|у)?\b|\bстаж[её]рск\w+|\bстажировк\w*|\bпрактикант\w*"),
]
# Контекст «про коллег» и «про рост»: уровень после этих слов не описывает кандидата.
COLLEAGUE_BEFORE = re.compile(
    r"(?:\b(?:с|со|под|у|среди|для)\s+(?:\S+\s+)?|под руководством\s+(?:\S+\s+){0,2}|"
    r"\b(?:до|уровня|перейти на|вырасти до|рост\w* до)\s+(?:уровня\s+)?)$"
)
COLLEAGUE_AFTER = re.compile(
    r"^[-–]?\s?(?:коллег|разработчик(?:ами|ов|и)\b|специалист(?:ами|ов|ы)\b|инженер(?:ами|ов|ы)\b|команд)"
)

# Лексика уровня: (грейд, шаблон, как назвать в объяснении). Ищется в тексте без заголовка; каждая
# сработавшая группа даёт LEXICON_WEIGHT голоса, но не больше LEXICON_CAP на грейд.
LEVEL_LEXICON = [
    ("junior", r"без опыта|опыт не (?:обязател|требует|важен)", "без опыта"),
    ("junior", r"\bстудент\w*|\bвыпускник\w*|\bначинающ\w+", "студенты / начинающие"),
    (
        "junior",
        r"(?:готовност|желани|стремлени)\w* (?:учиться|обучаться)|хо(?:тят|чет|чешь|тите) (?:учиться|вырасти)",
        "готовность учиться",
    ),
    ("junior", r"базов\w+ (?:знани|понимани|навык|уровн|представлени)|на базовом уровне", "базовые знания"),
    (
        "junior",
        r"наставник\w*|\bментор(?:а|ом|ы)?\b|менторск\w+ (?:сопровожд|поддержк)|под руководством",
        "наставник",
    ),
    (
        "junior",
        r"погружат\w*|погрузиться в (?:реальн|работ|проект)|дообучени\w*|прош\w+ курс|проходил\w* курс",
        "погружаться / дообучение",
    ),
    ("middle", r"самостоятельн\w*", "самостоятельно"),
    ("middle", r"глубок\w+ (?:знани|понимани)", "глубокое знание"),
    (
        "senior",
        r"архитектур\w* решени|(?:принимать|принятие) (?:архитектурн|техническ)\w* решени",
        "архитектурные решения",
    ),
    (
        "senior",
        r"менторить|(?:менторств|наставничеств|обучени)\w* (?:над |для )?(?:младш|джун|коллег)|растить (?:команд|джун)",
        "менторить",
    ),
    ("senior", r"техническ\w+ лидерств|техлидств", "техническое лидерство"),
    ("senior", r"(?:ищем|нужен|требуется)\s+опытн(?:ого|ый)\s+" + _ROLE, "опытный специалист"),
]
# Требования, сформулированные через практический опыт («Опыт работы с …» пункт за пунктом), без
# пометок для начинающих — признак Middle+.
EXPERIENCE_BULLETS_MIN = 4
LEXICON_WEIGHT, LEXICON_CAP = 0.5, 1.0
WEIGHT = {"experience": 2.0, "text_level": 1.5, "salary": 1.0}

# Стаж: «опыт … от 6 месяцев», «от 1,5 до 2 лет» (берётся нижняя граница), «≥1 год», «3+ года»,
# «больше двух лет», «от года». Число после «опыт…» в пределах фрагмента предложения.
_NUM = r"\d+(?:[.,]\d+)?|одного|двух|тр[её]х|четыр[её]х|пяти|шести|полу"
WORD_NUM = {"одного": 1, "двух": 2, "трех": 3, "трёх": 3, "четырех": 4, "четырёх": 4, "пяти": 5, "шести": 6}
EXPERIENCE_RE = re.compile(
    r"(?:опыт\w*|разрабатывал\w*|работал\w*|руководил\w*)[^.\n;]{0,60}?"
    r"(?:от|не менее|более|больше|минимум|свыше|≥|>=|\b)\s*"
    rf"(?P<a>{_NUM})\s*(?:-?х|-?ти)?(?:\s*(?:-|–|—|до)\s*(?P<b>{_NUM})\s*(?:-?х|-?ти)?)?\s*\+?\s*"
    r"(?P<u>год\w*|лет\b|years?|месяц\w*|мес\b)",
    re.I,
)
# «От 3 лет опыта бизнес-анализа», «5+ лет коммерческого опыта» — число перед словом «опыт».
EXPERIENCE_BEFORE_RE = re.compile(
    r"(?:от|не менее|более|больше|минимум|свыше|\b)\s*"
    rf"(?P<a>{_NUM})\s*(?:-?х|-?ти)?(?:\s*(?:-|–|—|до)\s*(?P<b>{_NUM})\s*(?:-?х|-?ти)?)?\s*\+?\s*"
    r"(?P<u>год\w*|лет\b|месяц\w*)\s+(?:\S+\s+){0,2}?опыт",
    re.I,
)
EXPERIENCE_ONE_RE = re.compile(
    r"опыт\w*[^.\n;]{0,60}?(?:от|не менее|более|больше|свыше)\s+(?P<u>полугода|года)\b", re.I
)
# Шкала «стаж → грейд» по dev-части bench3: «от 1 года» и «от 2 лет» — Middle, «от 3 лет» — Senior.
YEARS_SCALE = ((1.0, "junior"), (3.0, "middle"), (6.0, "senior"))
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
    grade_confidence: str = "low"  # high | medium | low — см. estimate_grade


@dataclass
class GradeSignal:
    kind: str  # title | experience | text_level | lexicon | salary
    grade: str
    weight: float
    reason: str


@dataclass
class GradeEstimate:
    grade: str | None
    confidence: str  # high | medium | low
    reason: str
    min_years: float | None
    signals: list[GradeSignal] = field(default_factory=list)


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


def _low(s: str) -> str:
    """casefold с сохранением переводов строк (`norm` склеивает строки, а пункты списка нужны)."""
    return re.sub(r"[ \t\u00a0]+", " ", s.casefold().replace("ё", "е"))


def _num(s: str) -> float:
    if s == "полу":
        return 0.5
    return float(WORD_NUM.get(s, 0) or s.replace(",", "."))


def parse_experience(text: str) -> float | None:
    """Требуемый стаж в годах: наибольшая из нижних границ («от 3 лет в QA, от 2 лет в автоматизации» → 3)."""
    t = _low(text)
    found = []
    for m in [*EXPERIENCE_RE.finditer(t), *EXPERIENCE_BEFORE_RE.finditer(t)]:
        y = _num(m.group("a"))
        if m.group("u").startswith("мес"):
            y /= 12
        if 0 < y <= 15:
            found.append(y)
    found += [0.5 if m.group("u") == "полугода" else 1.0 for m in EXPERIENCE_ONE_RE.finditer(t)]
    return round(max(found), 2) if found else None


def _experience_ru(y: float) -> str:
    if y < 1:
        n = max(1, round(y * 12))
        return (
            "от полугода"
            if n == 6
            else f"от {n} " + ("месяца" if n % 10 == 1 and n % 100 != 11 else "месяцев")
        )
    return years_from(y)


def _title_grade(title: str) -> str | None:
    """Уровень из заголовка; «Middle/Senior», «Junior/Junior+» — нижняя граница, как квалификация на площадке."""
    t = norm(title)
    hits = [gid for gid, cues in GRADE_CUES if any(re.search(c, t) for c in cues)]
    return min(hits, key=GRADE_ORDER.index) if hits else None


def _text_level(t: str) -> list[tuple[str, str]]:
    out = []
    for gid, pat in TEXT_LEVEL_CUES:
        for m in re.finditer(pat, t):
            if COLLEAGUE_BEFORE.search(t[max(0, m.start() - 40) : m.start()]) or COLLEAGUE_AFTER.search(
                t[m.end() : m.end() + 20]
            ):
                continue
            out.append((gid, m.group(0).strip()))
            break
    return out


def _salary_grade(spec: str | None, sal_from: int | None, sal_to: int | None) -> tuple[str, str] | None:
    cfg = get_catalog().raw.get("grade_salary")
    if not cfg or not (sal_from or sal_to):
        return None
    if sal_from and sal_to:
        mid, shown = math.sqrt(sal_from * sal_to), f"{sal_from // 1000}–{sal_to // 1000} тыс. ₽"
    elif sal_from:
        mid, shown = sal_from * 1.15, f"от {sal_from // 1000} тыс. ₽"
    else:
        mid, shown = sal_to * 0.85, f"до {sal_to // 1000} тыс. ₽"
    k = float(cfg["spec_factor"].get(spec, 1.0))
    med = [float(cfg["medians"][g]) * k for g in GRADE_ORDER]
    # по вилке Senior и Lead не различить: лидерство в деньгах почти не видно
    for i in range(GRADE_ORDER.index("senior")):
        if mid < math.sqrt(med[i] * med[i + 1]):
            return GRADE_ORDER[i], shown
    return "senior", shown


def estimate_grade(
    title: str,
    text: str,
    specialization: str | None = None,
    salary_from: int | None = None,
    salary_to: int | None = None,
) -> GradeEstimate:
    """Грейд вакансии — взвешенное голосование сигналов.

    Заголовок решает сам. Иначе голосуют: требуемый стаж, уровень в тексте (без упоминаний коллег),
    лексика уровня и вилка относительно медиан специализации (`grade_salary` в каталоге).
    Уверенность: high — заголовок или согласие двух и более сигналов; medium — один сигнал или
    перевес над несогласными; low — сильный конфликт или сигналов нет (тогда грейд не предлагается).
    """
    cat = get_catalog()
    years = parse_experience(title + "\n" + text)
    if tg := _title_grade(title):
        sig = GradeSignal("title", tg, math.inf, f"в заголовке указан уровень «{cat.grade(tg).name}»")
        return GradeEstimate(tg, "high", sig.reason, years, [sig])

    t = _low(text)
    signals: list[GradeSignal] = []
    if years is not None:
        g = next((g for lim, g in YEARS_SCALE if years < lim), "lead")
        signals.append(
            GradeSignal("experience", g, WEIGHT["experience"], f"требуемый опыт {_experience_ru(years)}")
        )
    if levels := _text_level(t):
        g, word = min(levels, key=lambda x: GRADE_ORDER.index(x[0]))
        signals.append(GradeSignal("text_level", g, WEIGHT["text_level"], f"в тексте — «{word}»"))
    lex: dict[str, list[str]] = {}
    for g, pat, label in LEVEL_LEXICON:
        if re.search(pat, t):
            lex.setdefault(g, []).append(label)
    bullets = len(re.findall(r"^\s*(?:[-•·*–—]\s*)?опыт\w*\b", t, re.M))
    if bullets >= EXPERIENCE_BULLETS_MIN and "junior" not in lex:
        lex.setdefault("middle", []).append(f"«опыт …» в {bullets} пунктах требований")
    for g, labels in lex.items():
        w = min(LEXICON_CAP, LEXICON_WEIGHT * len(labels))
        signals.append(
            GradeSignal(
                "lexicon", g, w, "лексика " + cat.grade(g).name + ": " + ", ".join(f"«{x}»" for x in labels)
            )
        )
    if sg := _salary_grade(specialization, salary_from, salary_to):
        g, shown = sg
        signals.append(
            GradeSignal("salary", g, WEIGHT["salary"], f"вилка {shown} типична для {cat.grade(g).name}")
        )

    if not signals:
        return GradeEstimate(None, "low", "уровень в тексте не указан — выберите вручную", years, [])
    votes: dict[str, float] = {}
    for s in signals:
        votes[s.grade] = votes.get(s.grade, 0.0) + s.weight
    priority = ("lexicon", "salary", "text_level", "experience")
    winner = max(
        votes, key=lambda g: (votes[g], max(priority.index(s.kind) for s in signals if s.grade == g))
    )
    support = [s for s in signals if s.grade == winner]
    oppose = [s for s in signals if s.grade != winner]
    ws, wo = votes[winner], sum(s.weight for s in oppose)
    if wo >= 0.75 * ws:
        conf = "low"
    elif len({s.kind for s in support}) >= 2 and wo < 0.5 * ws:
        conf = "high"
    else:
        conf = "medium"
    reason = "; ".join(s.reason for s in support)
    if oppose:
        reason += "; против: " + "; ".join(s.reason for s in oppose)
    return GradeEstimate(winner, conf, reason, years, signals)


def detect_grade(title: str, text: str) -> tuple[str | None, str | None, float | None]:
    """Совместимость: (грейд, объяснение, требуемый стаж) без учёта вилки и специализации."""
    e = estimate_grade(title, text)
    return e.grade, e.reason if e.grade else None, e.min_years


def parse_need(
    text: str, title: str = "", salary_from: int | None = None, salary_to: int | None = None
) -> ParsedNeed:
    """Разбор текста потребности. Вилка из полей формы (`salary_from/to`) важнее вилки в тексте."""
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

    sal_from, sal_to = (salary_from, salary_to) if (salary_from or salary_to) else parse_salary(full)
    est = estimate_grade(title, text, spec, sal_from, sal_to)
    grade, grade_reason, years = est.grade, est.reason, est.min_years
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
        check = {"high": "", "medium": " — проверьте", "low": " — сигналы расходятся, проверьте"}[
            est.confidence
        ]
        explanation.append(f"Грейд {cat.grade(grade).name}{check}: {grade_reason}")
    else:
        explanation.append(f"Грейд: {grade_reason}")

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
        grade_confidence=est.confidence,
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
