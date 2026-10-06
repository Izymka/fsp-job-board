"""Карточка кандидата и текст потребности — то, что видит работодатель (и асессор).

Карточка строится только из *наблюдаемых* данных платформы: категория и подоценки навыков по
тесту, заявленный стек, текст резюме, достижения ФСП, условия. Скрытая истина популяции
(реальная способность, накрутка стека) в карточку не попадает. Кандидат обезличен.

Одна и та же карточка подаётся на вход всем системам-бейзлайнам (BM25, эмбеддинги,
кросс-энкодер) и асессорам — сравнение честное: у всех одинаковая информация.
"""

from __future__ import annotations

from datetime import date

from ..catalog import get_catalog
from ..matching.scoring import CandidateFeatures

STATUS_TITLE = {
    "confirmed": "подтверждён",
    "uncertain": "частично",
    "weak": "не подтверждён",
}
RESULT_TITLE = {"winner": "победитель", "prize": "призёр", "finalist": "финалист", "participant": "участник"}


def _title(items, item_id: str) -> str:
    return next((x["title"] for x in items if x["id"] == item_id), item_id)


def _rub(v: int | None) -> str:
    return f"{v:,}".replace(",", " ") + " ₽" if v else "—"


def render_candidate(
    f: CandidateFeatures, today: date, *, alias: str, percentile: float | None = None
) -> str:
    cat = get_catalog()
    lines = [f"Кандидат {alias}"]
    spec = cat.specializations[f.specialization].title
    if f.grade:
        lines.append(f"Категория: {spec} · {cat.grade(f.grade).name} (грейд подтверждён тестом платформы)")
    else:
        lines.append(f"Категория: {spec} · грейд не подтверждён")
    if percentile is not None:
        lines.append(f"Результат теста: {round(percentile * 100)}-й перцентиль внутри своей категории")
    by_status: dict[str, list[str]] = {}
    for skill, status in sorted(f.skill_status.items()):
        if status in STATUS_TITLE:
            by_status.setdefault(status, []).append(cat.assessment_skills.get(skill, {}).get("title", skill))
    if by_status:
        parts = [f"{STATUS_TITLE[s]} — {', '.join(v)}" for s, v in by_status.items()]
        lines.append("Навыки по тесту: " + "; ".join(parts))
    if f.claimed:
        lines.append("Заявленный стек (самоописание): " + ", ".join(sorted(f.claimed)))
    if f.about:
        lines.append("Резюме: " + f.about.strip())
    if f.fsp is None:
        lines.append("ФСП: ID не привязан")
    elif not f.fsp:
        lines.append("ФСП: ID привязан, достижений нет")
    else:
        ach = []
        for a in sorted(f.fsp, key=lambda a: a.event_date, reverse=True):
            disc = _title(cat.fsp["disciplines"], a.discipline)
            lvl = _title(cat.fsp["levels"], a.level).lower()
            ach.append(f"{RESULT_TITLE.get(a.result, a.result)}, {lvl}, {disc.lower()}, {a.event_date.year}")
        lines.append("ФСП (подтверждено реестром): " + "; ".join(ach))
    lines.append(f"Ожидания по зарплате: от {_rub(f.salary_from)} до {_rub(f.salary_to)}")
    if f.work_formats:
        lines.append(
            "Формат работы: " + ", ".join(_title(cat.work_formats, x) for x in sorted(f.work_formats)).lower()
        )
    if f.industries:
        lines.append(
            "Интересные отрасли: " + ", ".join(_title(cat.industries, x) for x in sorted(f.industries))
        )
    status = _title(cat.search_statuses, f.search_status)
    if f.last_active:
        status += f", активность {max(0, (today - f.last_active).days)} дн. назад"
    lines.append(f"Статус поиска: {status}")
    return "\n".join(lines)


def render_need(title: str, text: str, company: str | None = None) -> str:
    head = f"Вакансия: {title}" + (f" — {company}" if company else "")
    return f"{head}\n\n{text.strip()}"
