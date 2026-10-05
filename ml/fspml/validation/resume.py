"""Валидация разбора резюме: синтетические PDF из известного JSON → парсер → пополевые метрики."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

import numpy as np

from ..catalog import DATA_DIR
from ..nlp.resume import parse_resume_pdf
from .population import spec_techs

FIRST = [
    "Алексей",
    "Мария",
    "Иван",
    "Анна",
    "Дмитрий",
    "Екатерина",
    "Сергей",
    "Ольга",
    "Никита",
    "Полина",
    "Артём",
    "Дарья",
]
LAST_M = ["Смирнов", "Кузнецов", "Попов", "Васильев", "Петров", "Соколов", "Морозов", "Волков"]
MIDDLE_M = ["Андреевич", "Сергеевич", "Игоревич", "Олегович"]
MIDDLE_F = ["Андреевна", "Сергеевна", "Игоревна", "Олеговна"]
CITIES = ["Москва", "Казань", "Новосибирск", "Екатеринбург", "Томск", "Самара", "Пермь"]
COMPANIES = ["ООО «Вектор»", "АО «Цифра»", "ИП Северов", "ООО «Платформа»", "ПАО «Связь»", "ООО «Датасфера»"]
MONTHS_RU = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]
TITLES = {
    "backend": "Backend-разработчик",
    "frontend": "Frontend-разработчик",
    "data_science": "Data Scientist",
    "qa": "QA-инженер",
    "devops": "DevOps-инженер",
    "analyst": "Системный аналитик",
    "mobile": "Android-разработчик",
}


@dataclass
class ResumeTruth:
    name: str
    email: str
    phone: str
    telegram: str
    city: str
    skills: set[str]
    years: float
    spec: str


MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_date(rng: random.Random, d: date) -> str:
    style = rng.choice(["month", "dot", "en"])
    if style == "month":
        return f"{MONTHS_RU[d.month - 1]} {d.year}"
    if style == "en":
        return f"{MONTHS_EN[d.month - 1]} {d.year}"
    return f"{d.month:02d}.{d.year}"


def _typo(rng: random.Random, word: str) -> str:
    """Опечатка: пропуск или удвоение буквы — проверяет нечёткий поиск."""
    if len(word) < 7 or not word.isalpha():
        return word
    i = rng.randint(1, len(word) - 2)
    return word[:i] + word[i + 1 :] if rng.random() < 0.5 else word[:i] + word[i] + word[i:]


def make_resume(rng: random.Random, today: date = date(2026, 10, 1)) -> tuple[ResumeTruth, bytes]:
    from fpdf import FPDF

    female = rng.random() < 0.5
    first = rng.choice(FIRST[1::2] if female else FIRST[0::2])
    last = rng.choice(LAST_M) + ("а" if female else "")
    middle = rng.choice(MIDDLE_F if female else MIDDLE_M)
    name = f"{last} {first} {middle}"
    spec = rng.choice(list(TITLES))
    techs = {t for t, _ in rng.sample(spec_techs(spec), min(len(spec_techs(spec)), rng.randint(4, 9)))}
    login = f"{first[:3].lower()}{rng.randint(10, 999)}"
    translit = str.maketrans("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "abvgdeezziiklmnoprstufhccss_y_eua")
    email = f"{login.translate(translit)}@mail.ru"
    phone = f"+7{rng.randint(900, 999)}{rng.randint(1000000, 9999999)}"
    tg = f"@{login.translate(translit)}_dev"
    city = rng.choice(CITIES)

    # 1–3 места работы, последовательно, последнее — по настоящее время
    n_jobs = rng.randint(1, 3)
    cur = today
    jobs = []
    months_total = 0
    for i in range(n_jobs):
        length = rng.randint(8, 40)
        end = cur
        y, m = end.year, end.month - length + 1
        while m <= 0:
            m += 12
            y -= 1
        start = date(y, m, 1)
        jobs.append((start, end, i == 0))
        months_total += length
        gap = rng.randint(1, 4)
        y2, m2 = start.year, start.month - gap
        while m2 <= 0:
            m2 += 12
            y2 -= 1
        cur = date(y2, m2, 1)

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("JB", "", str(DATA_DIR / "fonts" / "JetBrainsMono-Regular.ttf"))
    pdf.add_font("JB", "B", str(DATA_DIR / "fonts" / "JetBrainsMono-Bold.ttf"))
    pdf.set_font("JB", "B", 16)
    pdf.cell(0, 10, name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("JB", "", 10)
    pdf.cell(0, 6, TITLES[spec], new_x="LMARGIN", new_y="NEXT")
    contacts = [
        f"{city}",
        f"Телефон: {phone[:2]} ({phone[2:5]}) {phone[5:8]}-{phone[8:10]}-{phone[10:]}",
        f"Email: {email}",
        f"Telegram: {tg}",
    ]
    rng.shuffle(contacts)
    for c in contacts:
        pdf.cell(0, 6, c, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("JB", "B", 12)
    pdf.cell(0, 8, rng.choice(["Опыт работы", "Опыт", "Work experience"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("JB", "", 10)
    tech_list = sorted(techs)
    for start, end, current in jobs:
        pdf.cell(0, 6, f"{rng.choice(COMPANIES)} — {TITLES[spec]}", new_x="LMARGIN", new_y="NEXT")
        end_s = rng.choice(["по настоящее время", "н.в.", "Present"]) if current else _fmt_date(rng, end)
        pdf.cell(0, 6, f"{_fmt_date(rng, start)} — {end_s}", new_x="LMARGIN", new_y="NEXT")
        used = rng.sample(tech_list, min(3, len(tech_list)))
        pdf.multi_cell(
            0,
            6,
            "Задачи: разработка и поддержка, стек: " + ", ".join(used) + ".",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(2)
    pdf.set_font("JB", "B", 12)
    pdf.cell(
        0, 8, rng.choice(["Навыки", "Ключевые навыки", "Технологии", "Skills"]), new_x="LMARGIN", new_y="NEXT"
    )
    pdf.set_font("JB", "", 10)
    shown = [_typo(rng, t) if rng.random() < 0.2 else t for t in tech_list]
    pdf.multi_cell(0, 6, rng.choice([", ", " · ", "; "]).join(shown), new_x="LMARGIN", new_y="NEXT")
    data = bytes(pdf.output())
    truth = ResumeTruth(name, email, phone, tg, city, techs, round(months_total / 12, 1), spec)
    return truth, data


def evaluate(n: int = 60, seed: int = 17) -> dict:
    rng = random.Random(seed)
    field_hits = {k: 0 for k in ("name", "email", "phone", "telegram", "city", "specialization")}
    tp = fp = fn = 0
    year_err = []
    for _ in range(n):
        truth, pdf = make_resume(rng)
        r = parse_resume_pdf(pdf)
        field_hits["name"] += r.full_name == truth.name
        field_hits["email"] += r.email == truth.email
        field_hits["phone"] += r.phone == truth.phone
        field_hits["telegram"] += r.telegram == truth.telegram
        field_hits["city"] += r.city == truth.city
        field_hits["specialization"] += r.specialization_hint == truth.spec
        got = set(r.skills)
        tp += len(got & truth.skills)
        fp += len(got - truth.skills)
        fn += len(truth.skills - got)
        year_err.append(abs(r.experience_years - truth.years))
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    return {
        "n": n,
        "fields": {k: v / n for k, v in field_hits.items()},
        "skills_precision": prec,
        "skills_recall": rec,
        "skills_f1": 2 * prec * rec / max(1e-9, prec + rec),
        "experience_mae_years": float(np.mean(year_err)),
        "experience_within_0_5y": float(np.mean(np.array(year_err) <= 0.5)),
    }
