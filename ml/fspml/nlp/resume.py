"""Разбор резюме (PDF или текст) в структурированный профиль.

Конвейер: текст (pdfplumber) → секции по заголовкам → контакты (regex) → ФИО (эвристика по
первым строкам; natasha — если установлена) → технологии/софт-скиллы/роли по словарю → стаж
по интервалам дат с объединением пересечений → подсказка грейда правилами.

Результат только *подсказывает* значения в профиле и опросе — категорию кандидата определяет
тест (требование ТЗ).
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from datetime import date

from .skills import get_dictionary, norm
from .vacancy import years_ru

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
TG_RE = re.compile(
    r"(?:t\.me/|telegram[:\s]+|tg[:\s]+)@?([A-Za-z0-9_]{4,32})|(?<![\w.])@([A-Za-z][A-Za-z0-9_]{3,31})(?![\w.@])",
    re.I,
)
GH_RE = re.compile(r"github\.com/([A-Za-z0-9-]{1,39})", re.I)

MONTHS = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
PRESENT = r"(?:по\s+)?(?:настоящее\s+время|н\.\s*в\.|сейчас|по\s+наст\.?|present|now|current|текущ\w*)"
MONTH_WORD = r"(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-zа-я.]*"
DATE_TOKEN = rf"(?:(?:{MONTH_WORD})\s+\d{{4}}|\d{{1,2}}[./]\d{{4}}|\d{{4}})"
RANGE_RE = re.compile(rf"({DATE_TOKEN})\s*(?:-|–|—|по|to|until)\s*({DATE_TOKEN}|{PRESENT})", re.I)

SECTION_CUES = {
    "experience": r"опыт работы|опыт|work experience|experience|карьера",
    "education": r"образование|education",
    "skills": r"ключевые навыки|навыки|skills|технологии|стек|технический стек",
    "about": r"о себе|обо мне|about|summary|профиль",
    "achievements": r"достижения|соревнования|олимпиады|хакатоны|награды|achievements",
    "languages": r"языки|languages",
    "contacts": r"контакты|contacts",
}


@dataclass
class Job:
    title: str
    start: str
    end: str | None
    months: int


@dataclass
class ParsedResume:
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    telegram: str | None = None
    github: str | None = None
    city: str | None = None
    skills: list[str] = field(default_factory=list)
    skills_detail: dict[str, int] = field(default_factory=dict)
    soft_skills: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    experience_years: float = 0.0
    grade_hint: str | None = None
    grade_reason: str | None = None
    specialization_hint: str | None = None
    about: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def pdf_to_text(data: bytes) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:10]:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _parse_date(tok: str, *, end: bool) -> date | None:
    tok = tok.strip().lower()
    if re.fullmatch(PRESENT, tok, re.I):
        return date.today()
    m = re.fullmatch(rf"({MONTH_WORD})\s+(\d{{4}})", tok, re.I)
    if m:
        mon = MONTHS.get(m.group(1)[:3].lower())
        return date(int(m.group(2)), mon, 1) if mon else None
    m = re.fullmatch(r"(\d{1,2})[./](\d{4})", tok)
    if m and 1 <= int(m.group(1)) <= 12:
        return date(int(m.group(2)), int(m.group(1)), 1)
    m = re.fullmatch(r"\d{4}", tok)
    if m:
        y = int(tok)
        return date(y, 12 if end else 1, 1)
    return None


def _months(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + (b.month - a.month) + 1)


def _merge_months(intervals: list[tuple[date, date]]) -> int:
    """Суммарный стаж с объединением пересекающихся интервалов (совмещение работ не удваивает стаж)."""
    if not intervals:
        return 0
    iv = sorted(intervals)
    total = 0
    cur_s, cur_e = iv[0]
    for s, e in iv[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += _months(cur_s, cur_e)
            cur_s, cur_e = s, e
    return total + _months(cur_s, cur_e)


def _sections(lines: list[str]) -> dict[str, list[str]]:
    sec = "header"
    out: dict[str, list[str]] = {sec: []}
    for line in lines:
        s = line.strip().strip(":").strip()
        low = s.lower()
        hit = None
        if 0 < len(s) <= 40:
            for name, cue in SECTION_CUES.items():
                if re.fullmatch(rf"(?:{cue})(?:\s*[:/-].*)?", low):
                    hit = name
                    break
        if hit:
            sec = hit
            out.setdefault(sec, [])
            continue
        out.setdefault(sec, []).append(line)
    return out


NAME_RE = re.compile(
    r"^([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ][а-яё]+)(?:\s+([А-ЯЁ][а-яё]+))?$|^([A-Z][a-z]+)\s+([A-Z][a-z]+)$"
)
NOT_NAME = re.compile(
    r"резюме|resume|curriculum|разработчик|developer|engineer|инженер|аналитик|опыт|контакты|москва", re.I
)


def _guess_name(lines: list[str]) -> str | None:
    for line in lines[:8]:
        s = re.sub(r"\s+", " ", line.strip())
        if NAME_RE.match(s) and not NOT_NAME.search(s):
            return s
    try:  # natasha — опциональная зависимость
        from natasha import (  # noqa: F401
            PER,
            Doc,
            MorphVocab,
            NamesExtractor,
            NewsEmbedding,
            NewsNERTagger,
            Segmenter,
        )

        seg, emb = Segmenter(), NewsEmbedding()
        doc = Doc("\n".join(lines[:15]))
        doc.segment(seg)
        doc.tag_ner(NewsNERTagger(emb))
        for span in doc.spans:
            if span.type == PER and len(span.text.split()) >= 2:
                return span.text
    except Exception:
        pass
    return None


CITY_RE = re.compile(
    r"(?:г\.\s*|город\s+|проживание:\s*|location:\s*)?\b(Москва|Санкт-Петербург|Казань|Новосибирск|Екатеринбург|Нижний Новгород|Самара|Томск|Пермь|Омск|Уфа|Краснодар|Ростов-на-Дону|Воронеж|Сочи|Калининград|Иннополис)\b"
)


def parse_resume_text(text: str) -> ParsedResume:
    dic = get_dictionary()
    lines = [l for l in text.splitlines()]
    nonempty = [l for l in lines if l.strip()]
    res = ParsedResume()
    if len(text.strip()) < 50:
        res.warnings.append(
            "Мало текста: возможно, PDF — скан без текстового слоя. Заполните профиль вручную."
        )

    # Контакты
    if m := EMAIL_RE.search(text):
        res.email = m.group(0)
    if m := PHONE_RE.search(text):
        digits = re.sub(r"\D", "", m.group(0))
        res.phone = "+7" + digits[-10:]
    for m in TG_RE.finditer(text):
        handle = m.group(1) or m.group(2)
        if handle and (not res.email or handle.lower() not in res.email.lower()):
            res.telegram = "@" + handle
            break
    if m := GH_RE.search(text):
        res.github = m.group(1)
    if m := CITY_RE.search(text):
        res.city = m.group(1)
    res.full_name = _guess_name(nonempty)

    secs = _sections(lines)

    # Навыки: по всему тексту; в секции «навыки» — повышенный вес
    found = dic.extract(text)
    skills_sec = "\n".join(secs.get("skills", []))
    in_skills = set(dic.extract(skills_sec, fuzzy=False)) if skills_sec else set()
    ranked = sorted(found.values(), key=lambda m: (-(m.name in in_skills), -m.count, m.first_pos))
    res.skills = [m.name for m in ranked]
    res.skills_detail = {m.name: m.count for m in ranked}
    res.soft_skills = dic.extract_soft(text)

    # Опыт: интервалы дат и должности рядом с ними
    exp_lines = secs.get("experience") or lines
    intervals = []
    for i, line in enumerate(exp_lines):
        for m in RANGE_RE.finditer(line):
            a = _parse_date(m.group(1), end=False)
            b = _parse_date(m.group(2), end=True)
            if a and b and a <= b and a.year >= 1980:
                intervals.append((a, b))
                ctx = [l.strip() for l in exp_lines[max(0, i - 1) : i + 3] if l.strip()]
                title = next(
                    (c for c in ctx if not RANGE_RE.search(c) and len(c) <= 80), ctx[0] if ctx else ""
                )
                res.jobs.append(
                    Job(title=title[:120], start=m.group(1), end=m.group(2), months=_months(a, b))
                )
    res.experience_years = round(_merge_months(intervals) / 12, 1)

    roles = dic.extract_roles("\n".join(j.title for j in res.jobs) or "\n".join(nonempty[:5]))
    res.roles = [r for r, _ in roles]

    # Подсказка грейда: маркеры ролей важнее стажа, но не выше, чем позволяет стаж
    years = res.experience_years
    by_years = (
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
    order_ = ["intern", "junior", "middle", "senior", "lead"]
    role_grades = [g for _, g in roles]
    if role_grades:
        top_role = max(role_grades, key=order_.index)
        hint = top_role if order_.index(top_role) <= order_.index(by_years) + 1 else by_years
        res.grade_reason = f"последняя роль — {top_role.capitalize()}, стаж {years_ru(years)}"
    else:
        hint = by_years
        res.grade_reason = f"стаж {years_ru(years)}"
    res.grade_hint = hint

    # Подсказка специализации по технологиям
    from ..catalog import get_catalog

    scores = {s: 0.0 for s in get_catalog().specializations}
    for name, cnt in res.skills_detail.items():
        for s, w in dic.techs[name].spec.items():
            if s in scores:
                scores[s] += w * min(cnt, 3)
    if any(scores.values()):
        res.specialization_hint = max(scores, key=scores.get)

    about = "\n".join(secs.get("about", [])).strip()
    res.about = about[:1500] or None
    if not res.skills:
        res.warnings.append("Не удалось распознать технологии — добавьте стек вручную.")
    if not intervals:
        res.warnings.append("Не найдены периоды работы — проверьте стаж вручную.")
    return res


def parse_resume_pdf(data: bytes) -> ParsedResume:
    return parse_resume_text(pdf_to_text(data))


__all__ = ["ParsedResume", "parse_resume_pdf", "parse_resume_text", "norm"]
