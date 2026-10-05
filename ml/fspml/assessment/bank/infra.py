"""Семейства заданий: Git, Linux, Docker, Kubernetes, CI/CD."""

from __future__ import annotations

import math
import re

from ..items import family, number, order, single, text
from ._util import WORDS

# -------------------------------------------------------------------------------------------- Git


@family("git.commands", "git", 1, "Базовые команды Git")
def _(rng):
    cases = [
        ("создать новую ветку и сразу переключиться на неё", "git switch -c feature"),
        ("посмотреть изменения, ещё не добавленные в индекс", "git diff"),
        ("добавить изменения в последний коммит, не создавая новый", "git commit --amend"),
        ("временно убрать незакоммиченные изменения, чтобы переключиться на другую ветку", "git stash"),
        ("получить изменения с удалённого репозитория без слияния", "git fetch"),
        ("отменить опубликованный коммит новым коммитом", "git revert <sha>"),
        ("перенести один коммит из другой ветки в текущую", "git cherry-pick <sha>"),
    ]
    need, ans = rng.choice(cases)
    return single(
        rng, f"Какой командой {need}?", ans, [c[1] for c in cases if c[1] != ans] + ["git push --force"]
    )


@family("git.reset", "git", 3, "reset --soft / --mixed / --hard")
def _(rng):
    mode = rng.choice(["--soft", "--mixed", "--hard"])
    k = rng.randint(1, 3)
    answers = {
        "--soft": "HEAD сдвинут, изменения отменённых коммитов остаются в индексе (staged)",
        "--mixed": "HEAD сдвинут, изменения остаются в рабочей директории, но не в индексе",
        "--hard": "HEAD сдвинут, изменения отменённых коммитов удалены из индекса и рабочей директории",
    }
    return single(
        rng,
        f"Что произойдёт после `git reset {mode} HEAD~{k}` в ветке без незакоммиченных изменений?",
        answers[mode],
        [v for m, v in answers.items() if m != mode] + ["Будет создан новый коммит, отменяющий изменения"],
    )


@family("git.graph", "git", 3, "История коммитов: merge, squash, rebase")
def _(rng):
    m = rng.randint(1, 4)  # коммиты в main после ответвления
    f = rng.randint(2, 5)  # коммиты в feature
    base = rng.randint(3, 10)
    strategy = rng.choice(["merge --no-ff", "merge --squash + commit", "rebase + merge --ff-only"])
    total = (
        base
        + m
        + {"merge --no-ff": f + 1, "merge --squash + commit": 1, "rebase + merge --ff-only": f}[strategy]
    )
    prompt = (
        f"В `main` было {base} коммитов, затем от него ответвили `feature`. После этого в `main` добавили {m} коммит(а), "
        f"в `feature` — {f}. Ветку `feature` влили в `main` способом «{strategy}» (без конфликтов). "
        "Сколько коммитов станет достижимо из `main` (`git rev-list --count main`)?"
    )
    return number(prompt, total)


@family("git.conflicts", "git", 2, "Слияние и конфликты")
def _(rng):
    cases = [
        ("Две ветки изменили *разные* файлы", "Слияние пройдёт автоматически"),
        (
            "Две ветки изменили одну и ту же строку одного файла по-разному",
            "Возникнет конфликт, требующий ручного разрешения",
        ),
        ("Одна ветка удалила файл, другая изменила его", "Возникнет конфликт modify/delete"),
        ("Обе ветки внесли идентичное изменение в одну строку", "Слияние пройдёт автоматически"),
    ]
    sit, ans = rng.choice(cases)
    pool = [
        "Слияние пройдёт автоматически",
        "Возникнет конфликт, требующий ручного разрешения",
        "Возникнет конфликт modify/delete",
        "Git откажется сливать ветки без rebase",
    ]
    return single(rng, f"{sit}. Что произойдёт при `git merge`?", ans, [p for p in pool if p != ans])


# ------------------------------------------------------------------------------------------ Linux


def _perm_str(octal: str) -> str:
    out = ""
    for ch in octal:
        v = int(ch)
        out += ("r" if v & 4 else "-") + ("w" if v & 2 else "-") + ("x" if v & 1 else "-")
    return out


@family("linux.chmod", "linux", 1, "Права доступа chmod")
def _(rng):
    octal = "".join(str(rng.choice([7, 6, 5, 4, 0] if i else [7, 6, 5])) for i in range(3))
    to_str = rng.random() < 0.5
    if to_str:
        return text(
            f"Какую строку прав покажет `ls -l` для файла после `chmod {octal} file` (9 символов, без типа файла)?",
            _perm_str(octal),
            normalize="exact",
        )
    return text(
        f"Права файла в `ls -l`: `-{_perm_str(octal)}`. Какой восьмеричной маской (3 цифры) их можно установить через chmod?",
        octal,
        normalize="nospace",
    )


@family("linux.pipes", "linux", 2, "Конвейеры: grep, wc, sort, uniq")
def _(rng):
    levels = ["INFO", "WARN", "ERROR"]
    services = rng.sample(WORDS, 3)
    lines = [
        f"{rng.choice(levels)} {rng.choice(services)} request {rng.randint(1, 99)}"
        for _ in range(rng.randint(8, 12))
    ]
    lvl = rng.choice(levels)
    variant = rng.choice(["count", "uniq"])
    if variant == "count":
        cmd = f"grep -c '^{lvl}' app.log"
        ans = sum(1 for l in lines if l.startswith(lvl))
    else:
        cmd = f"grep '{lvl}' app.log | awk '{{print $2}}' | sort | uniq | wc -l"
        ans = len({l.split()[1] for l in lines if lvl in l})
    prompt = "Содержимое `app.log`:\n\n```\n" + "\n".join(lines) + "\n```\n\nЧто выведет команда?"
    return number(prompt, ans, code=cmd, code_lang="bash")


@family("linux.sed", "linux", 3, "sed и регулярные выражения")
def _(rng):
    w1, w2, w3 = rng.sample(WORDS, 3)
    line = f"{w1} {w2} {w1} {w3} {w1}"
    glob = rng.random() < 0.5
    cmd = f"echo '{line}' | sed 's/{w1}/{w3.upper()}/{'g' if glob else ''}'"
    ans = re.sub(w1, w3.upper(), line) if glob else line.replace(w1, w3.upper(), 1)
    return text("Что выведет команда?", ans, normalize="ci", code=cmd, code_lang="bash")


@family("linux.exit_codes", "linux", 3, "Коды возврата и && / ||")
def _(rng):
    a, b, c = rng.sample(["A", "B", "C", "D", "E"], 3)
    first = rng.choice(["true", "false"])
    mid = rng.choice(["true", "false"])
    cmd = f"{first} && echo {a} || echo {b}; {mid} || echo {c}"
    out = []
    if first == "true":
        out.append(a)
    else:
        out.append(b)
    if mid == "false":
        out.append(c)
    prompt = "Что выведет команда в bash? Введите строки вывода подряд без пробелов."
    return text(prompt, "".join(out), normalize="nospace", code=cmd, code_lang="bash")


@family("linux.processes", "linux", 4, "Процессы и сигналы")
def _(rng):
    cases = [
        ("Какой сигнал нельзя перехватить или проигнорировать?", "SIGKILL", ["SIGTERM", "SIGINT", "SIGHUP"]),
        ("Какой сигнал по умолчанию отправляет `kill <pid>`?", "SIGTERM", ["SIGKILL", "SIGINT", "SIGSTOP"]),
        (
            "Процесс в состоянии Z (zombie) — это…",
            "завершившийся процесс, код возврата которого не забрал родитель",
            [
                "процесс, ожидающий ввода-вывода",
                "процесс, остановленный сигналом SIGSTOP",
                "процесс с бесконечным циклом",
            ],
        ),
        (
            "Что показывает load average?",
            "среднее число процессов, готовых к выполнению или ждущих I/O",
            ["процент загрузки CPU", "объём занятой памяти", "число открытых файлов"],
        ),
        (
            "Что делает `nohup cmd &`?",
            "запускает команду в фоне, игнорируя SIGHUP при закрытии терминала",
            [
                "запускает команду с наивысшим приоритетом",
                "запускает команду от root",
                "запрещает команде писать в stdout",
            ],
        ),
    ]
    q, a, d = rng.choice(cases)
    return single(rng, q, a, d)


# ----------------------------------------------------------------------------------------- Docker


@family("docker.commands", "docker", 1, "Базовые команды Docker")
def _(rng):
    cases = [
        ("посмотреть запущенные контейнеры", "docker ps"),
        ("собрать образ из Dockerfile в текущей папке", "docker build -t app ."),
        ("открыть shell внутри запущенного контейнера", "docker exec -it app sh"),
        ("посмотреть логи контейнера", "docker logs app"),
        ("запустить контейнер в фоне с пробросом порта 8080→80", "docker run -d -p 8080:80 nginx"),
        ("удалить неиспользуемые образы", "docker image prune"),
    ]
    need, ans = rng.choice(cases)
    return single(rng, f"Какой командой {need}?", ans, [c[1] for c in cases if c[1] != ans])


@family("docker.layers", "docker", 2, "Кеширование слоёв при сборке")
def _(rng):
    good_order = rng.random() < 0.5
    if good_order:
        steps = [
            "FROM python:3.12-slim",
            "WORKDIR /app",
            "COPY requirements.txt .",
            "RUN pip install -r requirements.txt",
            "COPY . .",
            'CMD ["python", "main.py"]',
        ]
    else:
        steps = [
            "FROM python:3.12-slim",
            "WORKDIR /app",
            "COPY . .",
            "RUN pip install -r requirements.txt",
            'CMD ["python", "main.py"]',
        ]
    changed = rng.choice(["main.py", "requirements.txt"])
    # шаг инвалидируется, если он копирует изменённый файл, и все последующие тоже
    first_bad = None
    for i, s in enumerate(steps):
        if s.startswith("COPY") and (s.startswith("COPY . .") or changed in s):
            first_bad = i
            break
    rebuilt = len(steps) - first_bad
    prompt = (
        "Dockerfile:\n\n```dockerfile\n" + "\n".join(steps) + "\n```\n\n"
        f"Образ уже собирался, кеш есть. Изменили только файл `{changed}`. Сколько инструкций выполнится заново (не из кеша), включая CMD?"
    )
    return number(prompt, rebuilt)


@family("docker.entrypoint", "docker", 4, "ENTRYPOINT и CMD")
def _(rng):
    ep = rng.choice(['["python", "app.py"]', '["uvicorn", "main:app"]', '["./run.sh"]'])
    cmd = rng.choice(['["--port", "8000"]', '["--debug"]', '["--workers", "2"]'])
    override = rng.choice([None, "--help", "--port 9000"])
    import json

    parts = json.loads(ep) + (override.split() if override else json.loads(cmd))
    run = "docker run app" + (f" {override}" if override else "")
    prompt = f"В Dockerfile: `ENTRYPOINT {ep}` и `CMD {cmd}`. Какой процесс запустится командой `{run}`? Введите командную строку через пробел."
    return text(prompt, " ".join(parts), normalize="ci")


@family("docker.networking", "docker", 3, "Сеть и тома в Docker / Compose")
def _(rng):
    cases = [
        (
            "Как сервис `api` в docker-compose обратится к сервису `db` (Postgres) в той же сети?",
            "postgres://db:5432",
            [
                "postgres://localhost:5432",
                "postgres://127.0.0.1:5432",
                "postgres://host.docker.internal:15432",
            ],
        ),
        (
            "Контейнер запущен с `-p 8080:80`. Где приложение слушает внутри контейнера?",
            "На порту 80",
            ["На порту 8080", "На обоих портах", "На случайном порту"],
        ),
        (
            "Что произойдёт с данными в файловой системе контейнера после `docker rm`, если не использовался том?",
            "Данные будут удалены вместе с контейнером",
            [
                "Данные сохранятся в образе",
                "Данные переедут в именованный том",
                "Данные останутся в /var/lib/docker/volumes",
            ],
        ),
        (
            "Чем именованный том отличается от bind mount?",
            "Томом управляет Docker, bind mount монтирует конкретный путь хоста",
            ["Том доступен только для чтения", "Bind mount работает только на Linux", "Ничем"],
        ),
    ]
    q, a, d = rng.choice(cases)
    return single(rng, q, a, d)


# ------------------------------------------------------------------------------------- Kubernetes


@family("k8s.objects", "kubernetes", 2, "Объекты Kubernetes")
def _(rng):
    cases = [
        ("запустить stateless-приложение в N репликах с обновлением без простоя", "Deployment"),
        ("запустить базу данных со стабильными именами подов и своими томами", "StatefulSet"),
        ("запустить агент сбора логов на каждом узле", "DaemonSet"),
        ("выполнить разовую миграцию БД", "Job"),
        ("выполнять задачу по расписанию", "CronJob"),
        ("дать подам стабильный внутренний адрес и балансировку", "Service"),
        ("хранить пароль к БД", "Secret"),
        ("маршрутизировать внешний HTTP-трафик по хостам и путям", "Ingress"),
    ]
    need, ans = rng.choice(cases)
    return single(
        rng,
        f"Какой объект Kubernetes использовать, чтобы {need}?",
        ans,
        [c[1] for c in cases if c[1] != ans] + ["ConfigMap"],
    )


@family("k8s.rolling_update", "kubernetes", 3, "RollingUpdate: maxSurge / maxUnavailable")
def _(rng):
    r = rng.randint(3, 10)
    surge = rng.choice(["1", "2", "25%", "50%"])
    unavail = rng.choice(["0", "1", "25%"])

    def resolve(v: str, up: bool) -> int:
        if v.endswith("%"):
            x = r * int(v[:-1]) / 100
            return math.ceil(x) if up else math.floor(x)
        return int(v)

    s, u = resolve(surge, True), resolve(unavail, False)
    if s == 0 and u == 0:
        s = 1
        surge = "1"
    ask = rng.choice(["max", "min"])
    ans = r + s if ask == "max" else r - u
    what = "максимальное общее число подов" if ask == "max" else "минимальное число доступных подов"
    prompt = f"Deployment: replicas={r}, strategy RollingUpdate с maxSurge={surge}, maxUnavailable={unavail}. Каково {what} во время обновления?"
    return number(prompt, ans)


@family("k8s.scheduling", "kubernetes", 4, "Ресурсы: requests и размещение подов")
def _(rng):
    node_cpu = rng.choice([2000, 4000, 8000])
    node_mem = rng.choice([4096, 8192, 16384])
    sys_cpu = rng.choice([100, 200, 500])
    pod_cpu = rng.choice([250, 300, 500, 750])
    pod_mem = rng.choice([256, 512, 768, 1024])
    fit = min((node_cpu - sys_cpu) // pod_cpu, node_mem // pod_mem)
    prompt = (
        f"Узел: {node_cpu}m CPU и {node_mem} Mi памяти allocatable, уже занято системными подами {sys_cpu}m CPU (память — 0). "
        f"Под приложения: requests cpu={pod_cpu}m, memory={pod_mem}Mi (limits вдвое больше). Сколько таких подов планировщик разместит на узле?"
    )
    return number(prompt, fit)


@family("k8s.probes", "kubernetes", 3, "Liveness / readiness / startup пробы")
def _(rng):
    cases = [
        (
            "Под временно не готов принимать трафик (прогревает кеш), перезапускать его не нужно",
            "readinessProbe",
        ),
        ("Приложение зависло в дедлоке и нужно его перезапустить", "livenessProbe"),
        ("Приложение стартует 2 минуты, и обычная проба убивает его раньше", "startupProbe"),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng,
        f"{sit}. Какая проба нужна?",
        ans,
        ["readinessProbe", "livenessProbe", "startupProbe", "preStop hook"],
    )


# ------------------------------------------------------------------------------------------ CI/CD


@family("cicd.pipeline", "cicd", 2, "Порядок стадий конвейера")
def _(rng):
    variants = [
        [
            "Линтер и статический анализ",
            "Unit-тесты",
            "Сборка образа",
            "Деплой на staging",
            "Интеграционные / e2e-тесты",
            "Деплой в production",
        ],
        [
            "Checkout кода",
            "Установка зависимостей",
            "Unit-тесты",
            "Сборка артефакта",
            "Публикация артефакта в registry",
        ],
        [
            "Сборка образа",
            "Сканирование образа на уязвимости",
            "Публикация в registry",
            "Canary-деплой на 5% трафика",
            "Полная раскатка",
        ],
    ]
    steps = rng.choice(variants)
    return order(rng, "Расположите стадии CI/CD-конвейера в правильном порядке.", steps)


@family("cicd.strategies", "cicd", 3, "Стратегии деплоя")
def _(rng):
    cases = [
        (
            "Новая версия поднимается рядом со старой, трафик переключается целиком и мгновенно откатывается обратно",
            "Blue-green",
        ),
        ("Новую версию получает небольшая доля пользователей, доля растёт при хороших метриках", "Canary"),
        ("Поды заменяются постепенно, по несколько за раз", "Rolling update"),
        ("Старая версия полностью останавливается, затем запускается новая", "Recreate"),
        ("Функциональность выключена в коде флагом и включается без деплоя", "Feature flags"),
    ]
    desc, ans = rng.choice(cases)
    return single(rng, f"Как называется стратегия? {desc}.", ans, [c[1] for c in cases if c[1] != ans])


@family("cicd.semver", "cicd", 3, "Семантическое версионирование")
def _(rng):
    major, minor, patch = rng.randint(0, 5), rng.randint(0, 12), rng.randint(0, 20)
    change = rng.choice(["fix", "feat", "breaking"])
    if major == 0 and change == "breaking":
        major = 1
    desc = {
        "fix": "исправили ошибку без изменения API",
        "feat": "добавили новый эндпоинт, обратно совместимо",
        "breaking": "удалили устаревший параметр из публичного API",
    }[change]
    if change == "fix":
        ans = f"{major}.{minor}.{patch + 1}"
    elif change == "feat":
        ans = f"{major}.{minor + 1}.0"
    else:
        ans = f"{major + 1}.0.0"
    return text(
        f"Текущая версия библиотеки {major}.{minor}.{patch}. В релизе {desc}. Какой будет следующая версия по SemVer?",
        ans,
        normalize="nospace",
    )


@family("cicd.matrix", "cicd", 4, "Матрица сборок в CI")
def _(rng):
    pys = rng.sample(["3.10", "3.11", "3.12", "3.13"], rng.randint(2, 4))
    oss = rng.sample(["ubuntu-latest", "windows-latest", "macos-latest"], rng.randint(2, 3))
    excl = []
    if rng.random() < 0.7:
        excl.append((rng.choice(pys), rng.choice(oss)))
    incl = rng.randint(0, 2)
    jobs = len(pys) * len(oss) - len(excl) + incl
    yaml_ = (
        "strategy:\n  matrix:\n"
        f"    python: [{', '.join(repr(p) for p in pys)}]\n"
        f"    os: [{', '.join(oss)}]\n"
        + (
            "    exclude:\n" + "".join(f"      - python: '{p}'\n        os: {o}\n" for p, o in excl)
            if excl
            else ""
        )
        + (
            "    include:\n"
            + "".join(
                "      - python: '3.14-dev'\n        os: ubuntu-latest\n        experimental: true\n"
                for _ in range(1)
            )
            if incl >= 1
            else ""
        )
        + ("      - python: 'pypy3.10'\n        os: ubuntu-latest\n" if incl == 2 else "")
    )
    return number(
        "Сколько заданий (jobs) запустит GitHub Actions для этой матрицы?", jobs, code=yaml_, code_lang="yaml"
    )


@family("cicd.dora", "cicd", 5, "DORA-метрики")
def _(rng):
    deploys = rng.randint(20, 120)
    failed = rng.randint(1, max(2, deploys // 6))
    restore = [rng.randint(10, 240) for _ in range(failed)]
    variant = rng.choice(["cfr", "mttr"])
    if variant == "cfr":
        return number(
            f"За квартал было {deploys} деплоев в production, {failed} из них привели к инцидентам, потребовавшим отката или хотфикса. "
            "Каков Change Failure Rate (%)? Точность 0,1.",
            round(failed / deploys * 100, 2),
            tolerance=0.1,
        )
    return number(
        f"Время восстановления после инцидентов за квартал (мин): {', '.join(map(str, restore))}. Каково среднее время восстановления (MTTR, мин)? Точность 0,1.",
        round(sum(restore) / len(restore), 2),
        tolerance=0.1,
    )
