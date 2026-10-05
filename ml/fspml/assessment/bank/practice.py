"""Семейства заданий: тестирование (QA), анализ требований, продуктовые метрики, мобильная разработка."""

from __future__ import annotations

import math

from ..items import family, multi, number, order, single

# ------------------------------------------------------------------------------------------ QA


@family("qa.boundary", "testing", 1, "Граничные значения")
def _(rng):
    lo = rng.randint(1, 30)
    hi = lo + rng.randint(5, 80)
    field = rng.choice(["возраст", "количество товаров", "длина пароля", "сумма перевода (тыс.)"])
    correct = [lo - 1, lo, hi, hi + 1]
    wrong = [(lo + hi) // 2, lo + 2, hi - 2, 0 if lo > 2 else hi + 5]
    wrong = [w for w in wrong if w not in correct]
    return multi(
        rng,
        f"Поле «{field}» принимает целые значения от {lo} до {hi} включительно. Какие значения входят в минимальный набор "
        "для анализа граничных значений (двухточечный метод: граница и соседнее значение за ней)?",
        [str(x) for x in correct],
        [str(x) for x in wrong],
        n_options=6,
    )


@family("qa.equivalence", "testing", 2, "Классы эквивалентности")
def _(rng):
    parts = rng.randint(2, 4)
    bounds = sorted(rng.sample(range(2, 100), parts))
    desc = ", ".join(
        f"от 1 до {b}" if i == 0 else f"от {bounds[i - 1] + 1} до {b}" for i, b in enumerate(bounds)
    )
    non_numeric = rng.random() < 0.5
    total = (
        parts + 2 + (1 if non_numeric else 0)
    )  # допустимые диапазоны + ниже минимума + выше максимума (+ нечисловой ввод)
    extra = " Отдельно учитывается нечисловой ввод." if non_numeric else " Поле принимает только цифры."
    q = (
        f"Скидка зависит от суммы заказа (целое число тыс. ₽): диапазоны {desc}; значения меньше 1 и больше {bounds[-1]} недопустимы."
        f"{extra} Сколько классов эквивалентности (включая недопустимые) нужно покрыть?"
    )
    return number(q, total)


@family("qa.severity_priority", "testing", 2, "Severity и priority дефектов")
def _(rng):
    cases = [
        (
            "Опечатка в названии компании на главной странице перед запуском рекламной кампании",
            "Низкая серьёзность, высокий приоритет",
        ),
        (
            "Приложение падает при экспорте отчёта за 1990 год, которым никто не пользуется",
            "Высокая серьёзность, низкий приоритет",
        ),
        ("Невозможно оплатить заказ ни одним способом", "Высокая серьёзность, высокий приоритет"),
        ("Иконка в настройках смещена на 2 пикселя", "Низкая серьёзность, низкий приоритет"),
    ]
    sit, ans = rng.choice(cases)
    return single(rng, f"{sit}. Как классифицировать дефект?", ans, [c[1] for c in cases if c[1] != ans])


@family("qa.decision_table", "testing", 3, "Таблицы решений")
def _(rng):
    conds = rng.sample(
        [
            ("клиент новый", 2),
            ("способ оплаты", 3),
            ("есть промокод", 2),
            ("регион доставки", 4),
            ("подписка", 2),
            ("тип карты", 3),
        ],
        3,
    )
    total = math.prod(c[1] for c in conds)
    desc = "; ".join(f"«{c[0]}» — {c[1]} вариант(а)" for c in conds)
    return number(f"Условия: {desc}. Сколько правил (столбцов) в полной таблице решений?", total)


@family("qa.pairwise", "testing", 4, "Попарное тестирование")
def _(rng):
    variants = [
        ([2, 2, 2], 4),
        ([2, 2, 2, 2], 5),
        ([3, 3, 3], 9),
        ([3, 3, 3, 3], 9),
        ([2, 3], 6),
        ([3, 2, 2], 6),
    ]
    sizes, ans = rng.choice(variants)
    q = (
        f"Параметры имеют по {', '.join(map(str, sizes))} значения(й). Какое минимальное число тестов покрывает "
        "все пары значений любых двух параметров (pairwise)?"
    )
    return number(q, ans)


@family("qa.state_transition", "testing", 4, "Тестирование переходов состояний")
def _(rng):
    states = ["Создан", "Оплачен", "Отправлен", "Доставлен", "Отменён", "Возврат"]
    transitions = [
        ("Создан", "Оплачен"),
        ("Создан", "Отменён"),
        ("Оплачен", "Отправлен"),
        ("Оплачен", "Отменён"),
        ("Отправлен", "Доставлен"),
        ("Доставлен", "Возврат"),
    ]
    k = rng.randint(4, 6)
    tr = transitions[:k]
    used = sorted({s for t in tr for s in t}, key=states.index)
    q = (
        f"Заказ имеет состояния {', '.join(used)} и допустимые переходы: {', '.join(f'{a} → {b}' for a, b in tr)}. "
        "Сколько всего *недопустимых* переходов между различными состояниями нужно проверить для полного покрытия негативных сценариев (0-switch)?"
    )
    n = len(used)
    return number(q, n * (n - 1) - len(tr))


@family("qa.test_types", "testing", 3, "Виды и уровни тестирования")
def _(rng):
    cases = [
        ("После исправления бага проверяют, не сломалось ли что-то ещё", "Регрессионное тестирование"),
        ("Быстрая проверка, что сборка запускается и ключевые функции работают", "Smoke-тестирование"),
        ("Проверка, что система выдерживает 5000 одновременных пользователей", "Нагрузочное тестирование"),
        ("Тестирование без доступа к коду по спецификации", "Тестирование чёрного ящика"),
        ("Проверка взаимодействия сервиса заказов с сервисом оплаты", "Интеграционное тестирование"),
        ("Заказчик проверяет, что система решает его задачи", "Приёмочное тестирование"),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng, f"{sit}. Как называется этот вид тестирования?", ans, [c[1] for c in cases if c[1] != ans]
    )


@family("qa.api_checks", "testing", 3, "Тестирование API")
def _(rng):
    cases = [
        ("POST /users с уже существующим email", "409"),
        ("GET /users/abc, где id должен быть числом", "422"),
        ("DELETE /orders/5 пользователем без прав администратора", "403"),
        ("GET /orders/999999 — заказа не существует", "404"),
        ("POST /login с неверным паролем", "401"),
        ("Успешный POST /orders", "201"),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng,
        f"Какой код ответа ожидать в позитивно спроектированном REST API в сценарии: {sit}?",
        ans,
        ["200", "201", "400", "401", "403", "404", "409", "422", "500"],
    )


@family("qa.bug_report", "testing", 1, "Баг-репорт")
def _(rng):
    order_steps = rng.choice(
        [
            [
                "Заголовок: что сломано и где",
                "Шаги воспроизведения",
                "Ожидаемый результат",
                "Фактический результат",
                "Окружение и вложения",
            ],
            ["Предусловия", "Шаги воспроизведения", "Ожидаемый результат", "Фактический результат"],
        ]
    )
    return order(rng, "Расположите разделы баг-репорта в общепринятом порядке.", order_steps)


# -------------------------------------------------------------------------------- Requirements


@family("req.types", "requirements", 1, "Функциональные и нефункциональные требования")
def _(rng):
    fr = [
        "Пользователь может восстановить пароль по email",
        "Система формирует PDF-отчёт за выбранный период",
        "Работодатель может отправить приглашение кандидату",
    ]
    nfr = [
        "Страница поиска открывается не дольше 2 секунд при 100 пользователях",
        "Данные шифруются при передаче (TLS 1.2+)",
        "Доступность сервиса 99,9% в месяц",
        "Интерфейс доступен для экранных дикторов",
    ]
    ask_nfr = rng.random() < 0.5
    if ask_nfr:
        return multi(
            rng,
            "Какие требования являются **нефункциональными**?",
            rng.sample(nfr, 2),
            rng.sample(fr, 2),
            n_options=4,
        )
    return multi(
        rng,
        "Какие требования являются **функциональными**?",
        rng.sample(fr, 2),
        rng.sample(nfr, 2),
        n_options=4,
    )


@family("req.user_story", "requirements", 2, "User story и критерии приёмки")
def _(rng):
    role = rng.choice(["работодатель", "кандидат", "администратор"])
    cases = [
        (
            f"Как {role}, я хочу фильтровать список по статусу, чтобы быстрее находить нужные записи",
            "Корректная user story",
        ),
        ("Сделать кнопку синей и добавить API /filter", "Это техническая задача, а не user story"),
        (
            f"Как {role}, я хочу, чтобы система была удобной",
            "Неизмеримо: нет проверяемой ценности и критериев",
        ),
    ]
    text_, ans = rng.choice(cases)
    return single(
        rng,
        f"Оцените формулировку: «{text_}».",
        ans,
        [c[1] for c in cases if c[1] != ans] + ["Это эпик, его нельзя оценивать"],
    )


@family("req.gwt", "requirements", 2, "Критерии приёмки Given-When-Then")
def _(rng):
    steps = rng.choice(
        [
            [
                "Given кандидат прошёл тест на Middle",
                "When работодатель ищет Backend · Middle",
                "Then кандидат есть в выдаче",
            ],
            [
                "Given приглашение в статусе «отправлено»",
                "When кандидат открывает приглашение",
                "Then статус меняется на «просмотрено»",
            ],
            [
                "Given у пользователя не подтверждён email",
                "When он пытается войти",
                "Then показывается просьба подтвердить email",
            ],
        ]
    )
    return order(rng, "Соберите критерий приёмки в формате Gherkin.", steps)


@family("req.bpmn", "requirements", 3, "BPMN: шлюзы")
def _(rng):
    cases = [
        ("после шлюза выполняется ровно одна ветка по условию", "Исключающий шлюз (XOR)"),
        (
            "после шлюза все ветки выполняются параллельно, а затем синхронизируются",
            "Параллельный шлюз (AND)",
        ),
        ("после шлюза могут выполниться одна или несколько веток по условиям", "Включающий шлюз (OR)"),
        ("ветка выбирается по тому, какое событие наступит первым", "Событийный шлюз"),
    ]
    need, ans = rng.choice(cases)
    return single(
        rng, f"Какой элемент BPMN использовать, если {need}?", ans, [c[1] for c in cases if c[1] != ans]
    )


@family("req.uml_multiplicity", "requirements", 3, "Кратность связей и модели данных")
def _(rng):
    cases = [
        (
            "У кандидата может быть несколько приглашений, у приглашения — ровно один кандидат",
            "Один-ко-многим (1 — 0..*)",
        ),
        (
            "Кандидат владеет несколькими навыками, навыком владеют многие кандидаты",
            "Многие-ко-многим (через связующую таблицу)",
        ),
        (
            "У пользователя ровно один профиль, профиль принадлежит одному пользователю",
            "Один-к-одному (1 — 1)",
        ),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng, f"{sit}. Какая это связь?", ans, [c[1] for c in cases if c[1] != ans] + ["Наследование"]
    )


@family("req.integration", "requirements", 4, "Интеграции: синхронно или асинхронно")
def _(rng):
    cases = [
        (
            "Пользователь ждёт подтверждения оплаты на экране, ответ нужен за секунды",
            "Синхронный вызов API с таймаутом",
        ),
        ("Нужно разослать уведомления 100 000 пользователей", "Асинхронно через очередь сообщений"),
        ("ATS работодателя должна узнать о принятом приглашении", "Webhook (событие) с повторной доставкой"),
        (
            "Внешний реестр обновляет данные раз в сутки, нужны все изменения",
            "Периодическая выгрузка дельты по расписанию",
        ),
    ]
    sit, ans = rng.choice(cases)
    return single(rng, f"{sit}. Какой способ интеграции лучше?", ans, [c[1] for c in cases if c[1] != ans])


@family("req.prioritization", "requirements", 3, "Приоритизация требований")
def _(rng):
    reach, impact, conf, effort = (
        rng.randint(100, 5000),
        rng.choice([0.5, 1, 2, 3]),
        rng.choice([0.5, 0.8, 1.0]),
        rng.randint(1, 8),
    )
    rice = reach * impact * conf / effort
    q = f"Оцените фичу по RICE: Reach = {reach} пользователей/квартал, Impact = {impact}, Confidence = {int(conf * 100)}%, Effort = {effort} чел.-мес. Чему равен RICE-score? Точность 1."
    return number(q, round(rice, 2), tolerance=1)


# ------------------------------------------------------------------------------------ Metrics


@family("met.conversion", "metrics", 1, "Конверсия")
def _(rng):
    visits = rng.choice([1000, 2000, 4000, 5000, 8000])
    rate = rng.choice([0.02, 0.03, 0.05, 0.08, 0.12])
    orders = round(visits * rate)
    return number(
        f"На сайт зашли {visits} уникальных посетителей, {orders} из них оформили заказ. Какова конверсия в заказ (%)? Точность 0,01.",
        round(orders / visits * 100, 3),
        tolerance=0.01,
    )


@family("met.funnel", "metrics", 2, "Воронка")
def _(rng):
    n = rng.choice([10000, 20000, 50000])
    steps = [rng.choice([0.5, 0.6, 0.7, 0.8]) for _ in range(3)]
    names = ["регистрация", "заполнение профиля", "прохождение теста"]
    total = n * math.prod(steps)
    q = (
        f"{n} посетителей лендинга. Конверсии шагов: "
        + ", ".join(f"{nm} — {int(s * 100)}% от предыдущего шага" for nm, s in zip(names, steps))
        + ". Сколько человек пройдут тест?"
    )
    return number(q, round(total), tolerance=1)


@family("met.retention", "metrics", 2, "Retention и churn")
def _(rng):
    start = rng.choice([1000, 1200, 2000, 2500])
    left = rng.randint(50, start // 4)
    new = rng.randint(50, 400)
    variant = rng.choice(["churn", "retention"])
    if variant == "churn":
        return number(
            f"На начало месяца {start} платящих клиентов, за месяц {left} из них отменили подписку, пришло {new} новых. Каков churn rate за месяц (%)? Точность 0,1.",
            round(left / start * 100, 2),
            tolerance=0.1,
        )
    return number(
        f"В когорте {start} пользователей; через 7 дней вернулись {start - left}. Каков retention 7-го дня (%)? Точность 0,1.",
        round((start - left) / start * 100, 2),
        tolerance=0.1,
    )


@family("met.stickiness", "metrics", 2, "DAU/MAU")
def _(rng):
    mau = rng.choice([10000, 25000, 40000, 100000])
    dau = round(mau * rng.choice([0.1, 0.15, 0.2, 0.25, 0.35]))
    return number(
        f"DAU = {dau}, MAU = {mau}. Каков коэффициент липкости DAU/MAU (%)? Точность 0,1.",
        round(dau / mau * 100, 2),
        tolerance=0.1,
    )


@family("met.arpu", "metrics", 3, "ARPU, ARPPU, LTV")
def _(rng):
    users = rng.choice([10000, 20000, 50000])
    payers_share = rng.choice([0.02, 0.05, 0.1])
    revenue = rng.choice([500000, 1200000, 3000000])
    payers = round(users * payers_share)
    variant = rng.choice(["arpu", "arppu", "ltv"])
    if variant == "arpu":
        return number(
            f"За месяц: {users} активных пользователей, {payers} платящих, выручка {revenue} ₽. Найдите ARPU (₽). Точность 0,1.",
            round(revenue / users, 2),
            tolerance=0.1,
        )
    if variant == "arppu":
        return number(
            f"За месяц: {users} активных пользователей, {payers} платящих, выручка {revenue} ₽. Найдите ARPPU (₽). Точность 0,1.",
            round(revenue / payers, 2),
            tolerance=0.1,
        )
    arpu_m = rng.choice([100, 200, 300])
    churn = rng.choice([0.05, 0.1, 0.2])
    margin = rng.choice([0.5, 0.7, 1.0])
    ltv = arpu_m * margin / churn
    return number(
        f"Месячный ARPU = {arpu_m} ₽, маржинальность {int(margin * 100)}%, ежемесячный отток {int(churn * 100)}% (постоянный). Оцените LTV (₽) по формуле ARPU·маржа/churn. Точность 1.",
        round(ltv, 2),
        tolerance=1,
    )


@family("met.uplift", "metrics", 4, "A/B: относительный прирост и MDE")
def _(rng):
    a = rng.choice([0.04, 0.05, 0.08, 0.1])
    b = a * rng.choice([1.05, 1.1, 1.15, 1.2, 0.9])
    variant = rng.choice(["uplift", "mde_n"])
    if variant == "uplift":
        return number(
            f"Конверсия в контроле {a * 100:.2f}%, в тесте {b * 100:.2f}%. Каков относительный прирост (%)? Точность 0,1.",
            round((b / a - 1) * 100, 2),
            tolerance=0.1,
        )
    # приближённая формула n ≈ 16·p(1−p)/δ² на группу (α=0.05, мощность 80%)
    delta = abs(b - a)
    n = 16 * a * (1 - a) / delta**2
    return number(
        f"Базовая конверсия {a * 100:.1f}%, хотим обнаружить абсолютное изменение {delta * 100:.2f} п.п. По правилу n ≈ 16·p(1−p)/δ² "
        "(α = 0,05, мощность 80%) оцените размер каждой группы. Допускается погрешность 2%.",
        round(n),
        tolerance=max(5, n * 0.02),
    )


@family("met.choice", "metrics", 3, "Выбор метрики")
def _(rng):
    cases = [
        ("понять, насколько часто активные пользователи заходят в продукт", "DAU/MAU"),
        ("оценить, сколько денег приносит клиент за всё время", "LTV"),
        ("оценить, окупается ли привлечение клиентов", "LTV/CAC"),
        ("понять, на каком шаге оформления теряются пользователи", "Воронка конверсий по шагам"),
        ("оценить удовлетворённость пользователей", "NPS / CSAT"),
    ]
    need, ans = rng.choice(cases)
    return single(
        rng, f"Какая метрика лучше подходит, чтобы {need}?", ans, [c[1] for c in cases if c[1] != ans]
    )


# ------------------------------------------------------------------------------------- Mobile


@family("mob.android_lifecycle", "mobile", 1, "Жизненный цикл Activity")
def _(rng):
    variants = [
        ["onCreate", "onStart", "onResume"],
        ["onPause", "onStop", "onDestroy"],
        ["onCreate", "onStart", "onResume", "onPause", "onStop"],
    ]
    seq = rng.choice(variants)
    return order(rng, "Расположите колбэки жизненного цикла Android Activity в порядке вызова.", seq)


@family("mob.dp_px", "mobile", 2, "Плотность экрана: dp и px")
def _(rng):
    dpi_name, factor = rng.choice(
        [("mdpi", 1.0), ("hdpi", 1.5), ("xhdpi", 2.0), ("xxhdpi", 3.0), ("xxxhdpi", 4.0)]
    )
    dp = rng.choice([8, 16, 24, 48, 56, 72])
    return number(
        f"Сколько физических пикселей займёт элемент шириной {dp}dp на экране {dpi_name} (×{factor:g})?",
        dp * factor,
    )


@family("mob.threads", "mobile", 2, "Главный поток и асинхронность")
def _(rng):
    cases = [
        (
            "Где можно обновлять UI в Android/iOS?",
            "Только в главном (UI) потоке",
            ["В любом потоке", "Только в фоновом потоке", "В потоке сетевого запроса"],
        ),
        (
            "Что произойдёт при долгом сетевом запросе в главном потоке Android?",
            "Интерфейс зависнет, возможен ANR",
            ["Запрос выполнится быстрее", "Система автоматически перенесёт его в фон", "Ничего"],
        ),
        (
            "Чем в Kotlin выполнить сетевой запрос, не блокируя UI?",
            "Корутиной с Dispatchers.IO",
            ["Thread.sleep в onCreate", "Синхронным вызовом в onResume", "runOnUiThread"],
        ),
        (
            "Чем в Swift выполнить асинхронную загрузку данных?",
            "async/await (Task)",
            [
                "DispatchQueue.main.sync из главного потока",
                "Бесконечным циклом ожидания",
                "Notification без обработчика",
            ],
        ),
    ]
    q, a, d = rng.choice(cases)
    return single(rng, q, a, d)


@family("mob.storage", "mobile", 3, "Хранение данных на устройстве")
def _(rng):
    cases = [
        ("Хранить токен авторизации", "Keychain (iOS) / EncryptedSharedPreferences или Keystore (Android)"),
        (
            "Хранить кеш списка из 10 000 записей с поиском и фильтрами",
            "Локальная БД (Room / Core Data / SQLite)",
        ),
        ("Хранить флаг «онбординг пройден»", "UserDefaults / DataStore (key-value)"),
        (
            "Хранить загруженные изображения для офлайн-просмотра",
            "Файловая система в каталоге кеша приложения",
        ),
    ]
    need, ans = rng.choice(cases)
    return single(rng, f"Где лучше {need[0].lower() + need[1:]}?", ans, [c[1] for c in cases if c[1] != ans])


@family("mob.offline_sync", "mobile", 4, "Офлайн-режим и синхронизация")
def _(rng):
    cases = [
        (
            "Пользователь изменил заметку офлайн, а на сервере её изменили с другого устройства",
            "Обнаружить конфликт по версии и разрешить по стратегии (merge или выбор пользователя)",
        ),
        (
            "Запрос на создание заказа отправлен, ответ не пришёл из-за обрыва связи",
            "Повторить с тем же idempotency key",
        ),
        (
            "Нужно отправить действия, совершённые офлайн, после появления сети",
            "Очередь исходящих операций с фоновым воркером",
        ),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng,
        f"{sit}. Как поступить?",
        ans,
        [c[1] for c in cases if c[1] != ans] + ["Всегда перезаписывать сервер версией с устройства"],
    )


@family("mob.architecture", "mobile", 3, "Архитектура мобильного приложения")
def _(rng):
    cases = [
        (
            "Где хранить состояние экрана, чтобы оно пережило поворот устройства в Android?",
            "ViewModel",
            ["Activity", "Fragment arguments", "Глобальная переменная"],
        ),
        (
            "Какой слой отвечает за выбор источника данных (сеть или кеш)?",
            "Repository",
            ["View", "ViewModel", "Adapter"],
        ),
        (
            "Как в SwiftUI передать изменяемое состояние дочернему View?",
            "@Binding",
            ["@State в дочернем", "static var", "UserDefaults"],
        ),
    ]
    q, a, d = rng.choice(cases)
    return single(rng, q, a, d)


@family("mob.release", "mobile", 4, "Публикация и версии")
def _(rng):
    code = rng.randint(10, 200)
    cases = [
        (
            f"Текущий versionCode {code}. Каким должен быть versionCode следующей сборки для Google Play?",
            "Строго больше " + str(code),
            ["Любым", f"Равным {code}", "Меньше " + str(code)],
        ),
        (
            "Как раскатить релиз на часть пользователей в Google Play?",
            "Поэтапное развёртывание (staged rollout)",
            ["Отдельное приложение", "Только через TestFlight", "Нельзя"],
        ),
        (
            "Как раздать iOS-сборку бета-тестерам?",
            "TestFlight",
            ["Google Play Console", "Отправить .ipa в мессенджере", "App Store без ревью"],
        ),
    ]
    q, a, d = rng.choice(cases)
    return single(rng, q, a, d)
