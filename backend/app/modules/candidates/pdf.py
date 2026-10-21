"""Стандартизированный PDF-профиль кандидата (fpdf2, фирменный шрифт JetBrains Mono)."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fspml.catalog import DATA_DIR, get_catalog

from .models import CandidateProfile
from .service import anonymous_alias, category_label, revealed_contacts

PRIMARY = (64, 47, 255)
DARK = (27, 28, 33)
GREY = (120, 122, 128)
STATIC = Path(__file__).resolve().parents[2] / "static"

STATUS_RU = {
    "confirmed": "подтверждено",
    "uncertain": "частично",
    "weak": "не подтверждено",
    "no_data": "нет данных",
}


class _PDF(FPDF):
    def header(self):
        logo = STATIC / "logo.png"
        if logo.exists():
            self.image(str(logo), x=10, y=8, h=10)
        self.set_font("JB", "", 8)
        self.set_text_color(*GREY)
        self.set_xy(120, 10)
        self.cell(80, 5, "ФСП Job Board · профиль кандидата", align="R")
        self.set_draw_color(*PRIMARY)
        self.line(10, 22, 200, 22)
        self.set_y(26)

    def footer(self):
        self.set_y(-14)
        self.set_font("JB", "", 7)
        self.set_text_color(*GREY)
        self.cell(0, 5, f"Категория определена тестированием на платформе. Стр. {self.page_no()}", align="C")


def _section(pdf: FPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_font("JB", "B", 11)
    pdf.set_text_color(*PRIMARY)
    pdf.cell(0, 7, title.upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*DARK)
    pdf.set_font("JB", "", 9)


def render_profile_pdf(p: CandidateProfile, *, reveal_contacts: bool) -> bytes:
    cat = get_catalog()
    pdf = _PDF()
    pdf.add_font("JB", "", str(DATA_DIR / "fonts" / "JetBrainsMono-Regular.ttf"))
    pdf.add_font("JB", "B", str(DATA_DIR / "fonts" / "JetBrainsMono-Bold.ttf"))
    pdf.set_auto_page_break(True, 18)
    pdf.add_page()

    pdf.set_font("JB", "B", 18)
    pdf.set_text_color(*DARK)
    name, revealed = revealed_contacts(p) if reveal_contacts else (None, {})
    title = (name or "Кандидат") if reveal_contacts else anonymous_alias(p)
    pdf.multi_cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("JB", "", 10)
    if p.headline:
        pdf.multi_cell(0, 6, p.headline, new_x="LMARGIN", new_y="NEXT")
    label = category_label(p)
    pdf.set_text_color(*PRIMARY)
    pdf.set_font("JB", "B", 12)
    if label:
        when = p.confirmed_at.strftime("%d.%m.%Y") if p.confirmed_at else ""
        pdf.cell(0, 8, f"{label}  ✓ подтверждено тестом {when}", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 8, "Категория ещё не присвоена (тест не пройден)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*DARK)
    pdf.set_font("JB", "", 9)

    if reveal_contacts:
        contacts = [
            x
            for x in (
                revealed.get("email"),
                p.phone,
                p.telegram,
                f"github.com/{p.github}" if p.github else None,
                p.city,
            )
            if x
        ]
        if contacts:
            pdf.multi_cell(0, 5, " · ".join(contacts), new_x="LMARGIN", new_y="NEXT")
    elif p.city:
        pdf.cell(0, 5, p.city, new_x="LMARGIN", new_y="NEXT")

    _section(pdf, "Условия")
    fmts = (
        ", ".join(
            next((f["title"] for f in cat.work_formats if f["id"] == x), x) for x in (p.work_formats or [])
        )
        or "не указан"
    )
    sal = (
        f"{p.salary_from:,}–{p.salary_to:,} ₽".replace(",", " ")
        if p.salary_from and p.salary_to
        else (f"от {p.salary_from:,} ₽".replace(",", " ") if p.salary_from else "не указаны")
    )
    pdf.multi_cell(
        0,
        5,
        f"Формат: {fmts}\nОжидания: {sal}\nОпыт: {p.experience_years or 0:g} лет",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    if p.skill_scores:
        _section(pdf, "Навыки по результатам теста")
        for skill, s in sorted(p.skill_scores.items(), key=lambda kv: kv[1].get("status") != "confirmed"):
            title_ = cat.assessment_skills.get(skill, {}).get("title", skill)
            pdf.cell(
                0,
                5,
                f"{'●' if s.get('status') == 'confirmed' else '○'} {title_}: {STATUS_RU.get(s.get('status'), '—')} ({s.get('n', 0)} заданий)",
                new_x="LMARGIN",
                new_y="NEXT",
            )
    if p.stack:
        _section(pdf, "Стек (заявлено кандидатом)")
        pdf.multi_cell(0, 5, ", ".join(p.stack), new_x="LMARGIN", new_y="NEXT")

    _section(pdf, "Достижения ФСП")
    if p.fsp_id and p.show_fsp and reveal_contacts:
        pdf.cell(0, 5, f"ФСП ID: {p.fsp_id}", new_x="LMARGIN", new_y="NEXT")
    if not p.fsp_id:
        pdf.cell(0, 5, "ФСП ID не привязан", new_x="LMARGIN", new_y="NEXT")
    elif not p.show_fsp:
        pdf.cell(0, 5, "Скрыто настройками приватности", new_x="LMARGIN", new_y="NEXT")
    elif not p.fsp_achievements:
        pdf.cell(0, 5, "ФСП ID привязан, достижений пока нет", new_x="LMARGIN", new_y="NEXT")
    else:
        res = {x["id"]: x["title"] for x in cat.fsp["results"]}
        lvl = {x["id"]: x["title"] for x in cat.fsp["levels"]}
        for a in sorted(p.fsp_achievements, key=lambda a: a.get("date", ""), reverse=True)[:12]:
            pdf.multi_cell(
                0,
                5,
                f"{a.get('date', '')[:4]} · {res.get(a.get('result'), '')} · {a.get('title', '')} ({lvl.get(a.get('level'), '')})",
                new_x="LMARGIN",
                new_y="NEXT",
            )

    if p.experience:
        _section(pdf, "Опыт работы")
        for job in p.experience[:8]:
            period = f"{job.get('start', '')} — {job.get('end') or 'н.в.'}"
            pdf.set_font("JB", "B", 9)
            pdf.multi_cell(0, 5, f"{job.get('title', '')}  ({period})", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("JB", "", 9)
            if job.get("description"):
                pdf.multi_cell(0, 5, job["description"][:600], new_x="LMARGIN", new_y="NEXT")
    if p.about:
        _section(pdf, "О себе")
        pdf.multi_cell(0, 5, p.about[:1500], new_x="LMARGIN", new_y="NEXT")
    if p.soft_skills:
        _section(pdf, "Софт-скиллы")
        pdf.multi_cell(0, 5, ", ".join(p.soft_skills), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
