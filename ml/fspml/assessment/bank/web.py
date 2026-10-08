"""Семейства заданий: HTTP/REST/сети, безопасность, архитектура (языконезависимые якоря)."""

from __future__ import annotations

import math

from ..items import family, multi, number, single

# ------------------------------------------------------------------------------------------- HTTP


@family("http.status", "http", 1, "Коды ответа HTTP")
def _(rng):
    cases = [
        ("клиент запросил несуществующий ресурс", "404 Not Found"),
        ("запрос без токена к защищённому API", "401 Unauthorized"),
        ("пользователь аутентифицирован, но не имеет прав на ресурс", "403 Forbidden"),
        ("ресурс успешно создан через POST", "201 Created"),
        ("тело запроса не прошло валидацию", "422 Unprocessable Content"),
        ("клиент превысил лимит запросов", "429 Too Many Requests"),
        ("успешное удаление без тела ответа", "204 No Content"),
        ("попытка создать пользователя с уже занятым email", "409 Conflict"),
        ("ресурс навсегда переехал на новый URL", "301 Moved Permanently"),
        ("upstream-сервис не ответил вовремя за прокси", "504 Gateway Timeout"),
    ]
    situation, ans = rng.choice(cases)
    pool = [c[1] for c in cases if c[1] != ans] + ["400 Bad Request", "500 Internal Server Error"]
    return single(rng, f"Какой код ответа наиболее уместен, если {situation}?", ans, pool)


@family("http.idempotency", "http", 2, "Идемпотентность и безопасность методов")
def _(rng):
    methods = ["GET", "PUT", "DELETE", "POST", "PATCH", "HEAD", "OPTIONS"]
    prop = rng.choice(["idempotent", "safe"])
    shown = rng.sample(methods, 5)
    truth = {"idempotent": {"GET", "PUT", "DELETE", "HEAD", "OPTIONS"}, "safe": {"GET", "HEAD", "OPTIONS"}}[
        prop
    ]
    correct = [m for m in shown if m in truth]
    while not correct:
        shown = rng.sample(methods, 5)
        correct = [m for m in shown if m in truth]
    word = "идемпотентными" if prop == "idempotent" else "безопасными (не меняют состояние сервера)"
    return multi(
        rng,
        f"Какие из методов HTTP по спецификации являются {word}?",
        correct,
        [m for m in shown if m not in truth],
        n_options=5,
    )


@family("http.cache", "http", 2, "Кеширование: Cache-Control")
def _(rng):
    max_age = rng.choice([60, 120, 300, 600, 3600])
    age = rng.randint(0, max_age - 1)
    passed = rng.randint(5, max_age // 2)
    remaining = max(0, max_age - age - passed)
    prompt = (
        f"Ответ получен с заголовками `Cache-Control: max-age={max_age}` и `Age: {age}`. "
        f"Прошло ещё {passed} с. Сколько секунд ответ будет оставаться свежим в кеше браузера? (0 — уже устарел)"
    )
    return number(prompt, remaining)


@family("http.cors", "http", 3, "CORS: preflight-запросы")
def _(rng):
    method = rng.choice(["GET", "POST", "PUT", "DELETE"])
    ctype = rng.choice(["application/json", "text/plain", "application/x-www-form-urlencoded"])
    custom = rng.random() < 0.4
    simple_method = method in ("GET", "POST")
    simple_type = ctype != "application/json" or method == "GET"
    if method == "GET":
        ctype_line = ""
        simple_type = True
    else:
        ctype_line = f"Content-Type: {ctype}\n"
    needs = not (simple_method and simple_type and not custom)
    req = f"{method} https://api.other-domain.ru/items\n{ctype_line}" + (
        "X-Request-Id: 42\n" if custom else ""
    )
    ans = "Да, будет preflight OPTIONS" if needs else "Нет, запрос «простой»"
    other = "Нет, запрос «простой»" if needs else "Да, будет preflight OPTIONS"
    return single(
        rng,
        "Страница с https://app.example.ru делает fetch-запрос (без credentials). Отправит ли браузер предварительный запрос (preflight)?",
        ans,
        [
            other,
            "Зависит только от метода: preflight бывает у всех методов, кроме GET",
            "Нет, CORS не применяется к fetch",
        ],
        code=req,
        code_lang="http",
    )


@family("http.rest_design", "http", 3, "Проектирование REST API")
def _(rng):
    res = rng.choice(
        [("orders", "заказ"), ("users", "пользователя"), ("vacancies", "вакансию"), ("tickets", "заявку")]
    )
    ops = [
        (f"частично обновить {res[1]} с id 42", f"PATCH /{res[0]}/42"),
        ("получить список, отфильтрованный по статусу «active»", f"GET /{res[0]}?status=active"),
        (f"удалить {res[1]} с id 42", f"DELETE /{res[0]}/42"),
        (f"создать {res[1]}", f"POST /{res[0]}"),
        (f"полностью заменить {res[1]} с id 42", f"PUT /{res[0]}/42"),
    ]
    op, ans = rng.choice(ops)
    distractors = [o[1] for o in ops if o[1] != ans] + [
        f"POST /{res[0]}/42/update",
        f"GET /{res[0]}/delete?id=42",
    ]
    return single(rng, f"Какой эндпоинт соответствует REST-соглашениям, если нужно {op}?", ans, distractors)


@family("http.rtt", "http", 4, "Задержка установки соединения (TCP/TLS)")
def _(rng):
    rtt = rng.choice([20, 40, 50, 80, 100, 150])
    tls = rng.choice(["TLS 1.2", "TLS 1.3", "без TLS"])
    rtts = {"TLS 1.2": 2, "TLS 1.3": 1, "без TLS": 0}[tls] + 1 + 1  # TCP + TLS + запрос/ответ
    prompt = (
        f"RTT между клиентом и сервером {rtt} мс. Новое HTTP/1.1-соединение ({tls}, TCP без Fast Open, "
        "без возобновления сессии). Через сколько мс от начала подключения клиент получит первый байт ответа "
        "(обработка на сервере мгновенная, передача данных — пренебрежимо мала)?"
    )
    return number(prompt, rtts * rtt)


@family("http.token_bucket", "http", 4, "Rate limiting: token bucket")
def _(rng):
    cap = rng.randint(3, 6)
    rate = rng.choice([1, 2])
    times = sorted(rng.choice([0, 0, 0, 0.5, 1, 1.5, 2, 2.5, 3]) for _ in range(rng.randint(8, 11)))
    tokens = float(cap)
    last = 0.0
    rejected = 0
    for t in times:
        tokens = min(cap, tokens + (t - last) * rate)
        last = t
        if tokens >= 1:
            tokens -= 1
        else:
            rejected += 1
    prompt = (
        f"Лимитер «token bucket»: ёмкость {cap} токенов (в начале корзина полна), пополнение {rate} ток./с непрерывно. "
        f"Каждый запрос тратит 1 токен, без токена — отклоняется (429). Запросы приходят в моменты (с): {', '.join(str(t) for t in times)}. "
        "Сколько запросов будет отклонено?"
    )
    return number(prompt, rejected)


@family("http.backoff", "http", 5, "Повторные запросы: экспоненциальная задержка")
def _(rng):
    base = rng.choice([100, 200, 250, 500])
    factor = rng.choice([2, 3])
    retries = rng.randint(3, 5)
    cap = rng.choice([None, base * factor**2])
    waits = [base * factor**i for i in range(retries)]
    if cap:
        waits = [min(w, cap) for w in waits]
    cap_txt = f", но не более {cap} мс" if cap else ""
    prompt = (
        f"Клиент делает до {retries} повторов после неудачного запроса. Задержка перед i-м повтором (i = 0, 1, …) равна "
        f"{base}·{factor}^i мс{cap_txt}, без джиттера. Все попытки неудачны. Сколько мс суммарно клиент проведёт в ожидании?"
    )
    return number(prompt, sum(waits))


@family("http.dns_tcp", "http", 2, "Сетевые протоколы и порты")
def _(rng):
    cases = [
        (
            "Какой протокол транспортного уровня гарантирует доставку и порядок байтов?",
            "TCP",
            ["UDP", "IP", "ICMP"],
        ),
        ("Какой порт по умолчанию у HTTPS?", "443", ["80", "8080", "22"]),
        ("Какой порт по умолчанию у PostgreSQL?", "5432", ["3306", "6379", "27017"]),
        ("Какой порт по умолчанию у SSH?", "22", ["21", "23", "443"]),
        ("Какая запись DNS сопоставляет имя с IPv6-адресом?", "AAAA", ["A", "CNAME", "MX"]),
        ("Какая запись DNS указывает почтовый сервер домена?", "MX", ["TXT", "NS", "A"]),
        ("Сколько адресов узлов (без сети и broadcast) в подсети /28?", "14", ["16", "15", "30"]),
    ]
    q, ans, d = rng.choice(cases)
    return single(rng, q, ans, d)


# --------------------------------------------------------------------------------------- Security


@family("sec.injection", "security", 2, "SQL-инъекции")
def _(rng):
    field = rng.choice(["email", "login", "phone", "city"])
    langs = rng.choice(["python", "js"])
    if langs == "python":
        vuln = f"cur.execute(f\"SELECT * FROM users WHERE {field} = '{{{field}}}'\")"
        safe = f'cur.execute("SELECT * FROM users WHERE {field} = %s", ({field},))'
        also_vuln = f'cur.execute("SELECT * FROM users WHERE {field} = \'" + {field} + "\'")'
        safe2 = f"session.execute(select(User).where(User.{field} == {field}))"
    else:
        vuln = f"db.query(`SELECT * FROM users WHERE {field} = '${{{field}}}'`)"
        safe = f"db.query('SELECT * FROM users WHERE {field} = $1', [{field}])"
        also_vuln = f'db.query("SELECT * FROM users WHERE {field} = \'" + {field} + "\'")'
        safe2 = f"db.users.findOne({{ where: {{ {field} }} }})"
    ask_safe = rng.random() < 0.5
    if ask_safe:
        return multi(
            rng, "Какие варианты **защищены** от SQL-инъекции?", [safe, safe2], [vuln, also_vuln], n_options=4
        )
    return multi(
        rng, "Какие варианты **уязвимы** к SQL-инъекции?", [vuln, also_vuln], [safe, safe2], n_options=4
    )


@family("sec.passwords", "security", 3, "Хранение паролей")
def _(rng):
    correct = rng.choice(["argon2id с уникальной солью", "bcrypt с cost ≥ 10", "scrypt с уникальной солью"])
    wrong = [
        "SHA-256 от пароля",
        "MD5 с общей солью",
        "AES-шифрование пароля ключом из конфига",
        "Base64 от пароля",
        "SHA-1 с солью",
    ]
    return single(rng, "Как правильно хранить пароли пользователей в БД?", correct, wrong)


@family("sec.web_attacks", "security", 3, "Веб-атаки и защита")
def _(rng):
    cases = [
        (
            "XSS (внедрение скрипта через пользовательский ввод)",
            "экранирование вывода и Content-Security-Policy",
        ),
        ("CSRF (запрос от имени пользователя со стороннего сайта)", "SameSite-cookie и CSRF-токен"),
        (
            "SSRF (сервер ходит по URL, заданному пользователем)",
            "allowlist адресов и запрет внутренних сетей",
        ),
        (
            "IDOR (доступ к чужому объекту по id в URL)",
            "проверка владельца объекта на сервере для каждого запроса",
        ),
        ("брутфорс паролей", "ограничение попыток, задержки и 2FA"),
        ("clickjacking", "заголовок X-Frame-Options / frame-ancestors"),
    ]
    attack, defense = rng.choice(cases)
    return single(
        rng,
        f"Какая мера в первую очередь защищает от атаки: {attack}?",
        defense,
        [c[1] for c in cases if c[1] != defense],
    )


@family("sec.jwt", "security", 4, "JWT: типичные ошибки")
def _(rng):
    cases = [
        ("Сервер принимает токены с заголовком `alg: none`", "Подделка любого токена без ключа"),
        ("Секрет HS256 — строка `secret` из примера в документации", "Подбор секрета и выпуск своих токенов"),
        ("Сервер проверяет подпись, но не поле `exp`", "Украденный токен действует бессрочно"),
        ("Сервер не проверяет поле `aud`", "Токен, выпущенный для другого сервиса, принимается этим"),
        (
            "В payload JWT положили пароль пользователя",
            "Утечка пароля: payload только закодирован, не зашифрован",
        ),
    ]
    issue, risk = rng.choice(cases)
    return single(rng, f"Чем опасна ситуация: {issue}?", risk, [c[1] for c in cases if c[1] != risk])


@family("sec.owasp_auth", "security", 2, "Аутентификация и сессии")
def _(rng):
    cases = [
        (
            "Где безопаснее хранить refresh-токен в браузерном SPA?",
            "В HttpOnly Secure cookie",
            ["В localStorage", "В URL-параметре", "В глобальной переменной JS"],
        ),
        (
            "Что означает флаг cookie HttpOnly?",
            "Cookie недоступна из JavaScript",
            [
                "Cookie передаётся только по HTTP",
                "Cookie шифруется браузером",
                "Cookie удаляется при закрытии вкладки",
            ],
        ),
        (
            "Что такое принцип наименьших привилегий?",
            "Выдавать только те права, которые необходимы для задачи",
            [
                "Давать всем права администратора на время разработки",
                "Использовать минимальное число паролей",
                "Хранить меньше логов",
            ],
        ),
        (
            "Зачем нужна соль при хешировании пароля?",
            "Чтобы одинаковые пароли давали разные хеши и не работали радужные таблицы",
            ["Чтобы хеш можно было расшифровать", "Чтобы хеш стал короче", "Чтобы ускорить проверку"],
        ),
    ]
    q, a, d = rng.choice(cases)
    return single(rng, q, a, d)


# ----------------------------------------------------------------------------------- Architecture


@family("arch.capacity", "architecture", 4, "Оценка нагрузки и объёма данных")
def _(rng):
    dau = rng.choice([200_000, 500_000, 1_000_000, 2_000_000, 5_000_000])
    per_user = rng.choice([5, 10, 20, 40])
    size_kb = rng.choice([1, 2, 4, 10])
    days = rng.choice([30, 90, 365])
    ask = rng.choice(["rps", "storage"])
    if ask == "rps":
        avg = dau * per_user / 86_400
        peak = rng.choice([2, 3, 5])
        ans = round(avg * peak)
        prompt = (
            f"Сервисом пользуются {dau:,} человек в день, каждый делает в среднем {per_user} запросов на запись. "
            f"Пиковая нагрузка в {peak} раза выше средней. Оцените пиковый RPS на запись (округлите до целого; допускается погрешность 5%)."
        ).replace(",", " ")
        return number(prompt, ans, tolerance=max(1.0, ans * 0.05))
    total_gb = dau * per_user * size_kb * days / 1_000_000
    prompt = (
        f"{dau:,} активных пользователей в день, каждый создаёт {per_user} записей по {size_kb} КБ. "
        f"Сколько ГБ данных накопится за {days} дней без репликации и сжатия (1 ГБ = 10⁶ КБ)? Допускается погрешность 5%."
    ).replace(",", " ")
    return number(prompt, round(total_gb, 1), tolerance=max(0.5, total_gb * 0.05))


@family("arch.availability", "architecture", 5, "Доступность составной системы")
def _(rng):
    a1 = rng.choice([99.0, 99.5, 99.9, 99.95])
    a2 = rng.choice([99.0, 99.5, 99.9])
    replicas = rng.choice([2, 3])
    p1, p2 = a1 / 100, a2 / 100
    p2_par = 1 - (1 - p2) ** replicas
    total = p1 * p2_par * 100
    prompt = (
        f"Запрос последовательно проходит через API-шлюз (доступность {a1}%) и сервис, развёрнутый в {replicas} независимых "
        f"репликах (каждая — {a2}%; запрос успешен, если жива хотя бы одна). Какова итоговая доступность в процентах? "
        "Ответ с точностью до 0,01."
    )
    return number(prompt, round(total, 3), tolerance=0.011)


@family("arch.consistent_hashing", "architecture", 5, "Шардирование: доля перемещаемых ключей")
def _(rng):
    n = rng.randint(3, 9)
    scheme = rng.choice(["hash", "consistent"])
    if scheme == "hash":
        # при hash(key) mod n → mod (n+1) остаётся на месте доля 1/(n+1)
        moved = 100 * (1 - 1 / (n + 1))
        desc = "шард = hash(key) mod N"
    else:
        moved = 100 / (n + 1)
        desc = "консистентное хеширование с большим числом виртуальных узлов"
    prompt = (
        f"Данные равномерно распределены по {n} шардам, схема: {desc}. Добавили ещё один шард. "
        "Какая доля ключей (в %) в среднем сменит шард? Допускается погрешность 1 п.п."
    )
    return number(prompt, round(moved, 1), tolerance=1.0)


@family("arch.patterns", "architecture", 3, "Архитектурные паттерны")
def _(rng):
    cases = [
        ("гарантировать отправку события в брокер после коммита транзакции в БД", "Transactional Outbox"),
        ("выполнить распределённую бизнес-транзакцию через несколько сервисов с компенсациями", "Saga"),
        ("не перегружать упавший сервис повторными запросами", "Circuit Breaker"),
        ("разделить модели записи и чтения", "CQRS"),
        ("безопасно повторять POST-запрос оплаты при сетевых сбоях", "Idempotency Key"),
        ("постепенно заменить монолит новыми сервисами", "Strangler Fig"),
        ("снизить нагрузку на БД при частых чтениях одинаковых данных", "Cache-Aside"),
    ]
    need, ans = rng.choice(cases)
    return single(
        rng, f"Какой паттерн подходит, если нужно {need}?", ans, [c[1] for c in cases if c[1] != ans]
    )


@family("arch.cap", "architecture", 4, "CAP и согласованность")
def _(rng):
    cases = [
        ("При сетевом разделении система отвечает на все запросы, допуская устаревшие данные", "AP"),
        ("При сетевом разделении система отказывает в части запросов, но не отдаёт устаревшие данные", "CP"),
    ]
    desc, ans = rng.choice(cases)
    return single(
        rng,
        f"Какой выбор по теореме CAP описан? {desc}.",
        ans,
        ["AP", "CP", "CA", "Теорема CAP здесь неприменима"],
    )


@family("arch.queues", "architecture", 3, "Очереди и семантика доставки")
def _(rng):
    cases = [
        (
            "Консьюмер подтверждает сообщение (ack) до обработки, затем падает",
            "Сообщение потеряно (at-most-once)",
        ),
        (
            "Консьюмер обрабатывает сообщение, падает до ack, брокер доставляет повторно",
            "Возможна повторная обработка (at-least-once)",
        ),
        (
            "Нужно обработать каждое сообщение ровно один раз при доставке at-least-once",
            "Идемпотентная обработка (дедупликация по ключу)",
        ),
        (
            "Сообщения одного заказа должны обрабатываться строго по порядку в Kafka",
            "Ключ партиционирования = id заказа",
        ),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng,
        f"{sit}. Что верно?",
        ans,
        [c[1] for c in cases if c[1] != ans] + ["Брокер гарантирует exactly-once без доработок"],
    )


@family("arch.latency_percentiles", "architecture", 4, "Перцентили задержек")
def _(rng):
    n = 100
    base = sorted(rng.randint(20, 80) for _ in range(n - 5)) + sorted(rng.randint(300, 900) for _ in range(5))
    p = rng.choice([95, 96, 97, 98, 99])
    ans = base[math.ceil(p / 100 * n) - 1]
    prompt = (
        f"Из 100 запросов 95 выполнились за 20–80 мс (самый медленный из них — {base[94]} мс), "
        f"а 5 самых медленных — за {', '.join(map(str, base[-5:]))} мс. "
        f"Чему равен p{p} (метод nearest-rank: значение с номером ⌈p/100·N⌉ в отсортированном по возрастанию списке)?"
    )
    return number(prompt, ans)


@family("sec.access_control", "security", 3, "Контроль доступа к объектам")
def _(rng):
    cases = [
        (
            "Пользователь меняет в адресе /api/invoices/1043 номер на 1044 и видит чужой счёт",
            "IDOR: на сервере проверять, что объект принадлежит пользователю",
        ),
        (
            "Для обычных пользователей скрыли кнопку «Удалить», а эндпоинт DELETE доступен всем",
            "Скрытия в интерфейсе недостаточно: права проверяются на сервере",
        ),
        (
            "При обновлении профиля клиент может прислать поле role=admin, и оно сохранится",
            "Mass assignment: принимать только разрешённые поля (явная схема запроса)",
        ),
    ]
    sit, a = rng.choice(cases)
    return single(
        rng,
        f"{sit}. В чём уязвимость и как её закрыть?",
        a,
        [c[1] for c in cases if c[1] != a] + ["Включить HTTPS"],
    )


@family("sec.secrets", "security", 2, "Секреты в коде и конфигурации")
def _(rng):
    cases = [
        (
            "API-ключ платёжного сервиса случайно закоммитили в публичный репозиторий",
            "Немедленно отозвать и перевыпустить ключ, затем вычистить историю",
        ),
        (
            "Где хранить пароль БД для приложения в Kubernetes?",
            "В Secret/хранилище секретов, передавать через переменные окружения или файл",
        ),
        (
            "Приложение пишет в лог тело запроса авторизации целиком",
            "Маскировать пароли и токены перед записью в лог",
        ),
    ]
    q, a = rng.choice(cases)
    return single(
        rng, q, a, [c[1] for c in cases if c[1] != a] + ["Закодировать секрет в base64 прямо в коде"]
    )
