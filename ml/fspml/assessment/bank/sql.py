"""Семейства заданий: SQL. Данные генерируются, ответ вычисляется запросом в in-memory SQLite."""

from __future__ import annotations

import random

from ..items import family, number, single, text
from ._util import CITIES, DEPTS, NAMES, run_sql, sql_insert

ASK_NUM = "Сколько строк (или какое число) вернёт запрос? Введите число."


def _employees(rng: random.Random, n: int, with_nulls: bool = False):
    names = rng.sample(NAMES, n)
    rows = []
    for name in names:
        bonus = None if (with_nulls and rng.random() < 0.35) else rng.choice([0, 5, 10, 15])
        rows.append((name, rng.choice(DEPTS[:4]), rng.randrange(80, 300, 10), bonus))
    setup = "CREATE TABLE employees (name TEXT, dept TEXT, salary INTEGER, bonus INTEGER);\n" + sql_insert(
        "employees", ["name", "dept", "salary", "bonus"], rows
    )
    return setup, rows


def _table_md(cols, rows) -> str:
    def cell(v):
        return "NULL" if v is None else str(v)

    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "\n".join("| " + " | ".join(cell(v) for v in r) + " |" for r in rows)


@family("sql.where", "sql", 1, "Фильтрация WHERE")
def _(rng):
    setup, rows = _employees(rng, rng.randint(6, 8))
    t = rng.randrange(120, 260, 10)
    dept = rng.choice(DEPTS[:4])
    op = rng.choice(["AND", "OR"])
    q = f"SELECT COUNT(*) FROM employees WHERE salary > {t} {op} dept = '{dept}';"
    ans = run_sql(setup, q)[0][0]
    prompt = f"Таблица `employees` (зарплата в тыс. ₽):\n\n{_table_md(['name', 'dept', 'salary', 'bonus'], rows)}\n\n{ASK_NUM}"
    return number(prompt, ans, code=q, code_lang="sql")


@family("sql.null_count", "sql", 2, "NULL в агрегатах")
def _(rng):
    setup, rows = _employees(rng, rng.randint(6, 8), with_nulls=True)
    while not any(r[3] is None for r in rows):
        setup, rows = _employees(rng, rng.randint(6, 8), with_nulls=True)
    expr = rng.choice(
        [
            "COUNT(*) - COUNT(bonus)",
            "COUNT(bonus)",
            "SUM(CASE WHEN bonus > 0 THEN 1 ELSE 0 END)",
            "COUNT(DISTINCT bonus)",
        ]
    )
    q = f"SELECT {expr} FROM employees;"
    ans = run_sql(setup, q)[0][0]
    prompt = f"Таблица `employees`:\n\n{_table_md(['name', 'dept', 'salary', 'bonus'], rows)}\n\nКакое число вернёт запрос?"
    return number(prompt, ans, code=q, code_lang="sql")


@family("sql.group_by", "sql", 2, "Группировка и агрегаты")
def _(rng):
    setup, rows = _employees(rng, rng.randint(7, 9))
    agg = rng.choice(["AVG(salary)", "SUM(salary)", "MAX(salary)", "COUNT(*)"])
    desc = rng.random() < 0.5
    q = (
        f"SELECT dept FROM employees GROUP BY dept\n"
        f"ORDER BY {agg} {'DESC' if desc else 'ASC'}, dept\nLIMIT 1;"
    )
    ans = run_sql(setup, q)[0][0]
    prompt = f"Таблица `employees`:\n\n{_table_md(['name', 'dept', 'salary', 'bonus'], rows)}\n\nКакое значение `dept` вернёт запрос?"
    return text(prompt, ans, normalize="ci", code=q, code_lang="sql")


@family("sql.having", "sql", 3, "HAVING против WHERE")
def _(rng):
    setup, rows = _employees(rng, rng.randint(8, 10))
    t = rng.randrange(100, 220, 10)
    k = rng.randint(1, 2)
    q = f"SELECT dept, COUNT(*) FROM employees\nWHERE salary >= {t}\nGROUP BY dept\nHAVING COUNT(*) > {k};"
    ans = len(run_sql(setup, q))
    prompt = f"Таблица `employees`:\n\n{_table_md(['name', 'dept', 'salary', 'bonus'], rows)}\n\nСколько строк вернёт запрос?"
    return number(prompt, ans, code=q, code_lang="sql")


@family("sql.left_join", "sql", 3, "LEFT JOIN и строки без пары")
def _(rng):
    users = [(i + 1, n) for i, n in enumerate(rng.sample(NAMES, rng.randint(4, 6)))]
    orders = []
    for oid in range(1, rng.randint(5, 8) + 1):
        uid = rng.choice([u[0] for u in users] + [99])
        orders.append((oid, uid, rng.randrange(100, 1000, 50)))
    setup = (
        "CREATE TABLE users (id INTEGER, name TEXT);\nCREATE TABLE orders (id INTEGER, user_id INTEGER, amount INTEGER);\n"
        + sql_insert("users", ["id", "name"], users)
        + "\n"
        + sql_insert("orders", ["id", "user_id", "amount"], orders)
    )
    variant = rng.choice(["count", "null", "where_trap"])
    if variant == "count":
        q = "SELECT COUNT(*) FROM users u LEFT JOIN orders o ON o.user_id = u.id;"
    elif variant == "null":
        q = "SELECT COUNT(*) FROM users u LEFT JOIN orders o ON o.user_id = u.id WHERE o.id IS NULL;"
    else:
        t = rng.randrange(300, 700, 50)
        q = f"SELECT COUNT(*) FROM users u LEFT JOIN orders o ON o.user_id = u.id WHERE o.amount > {t};"
    ans = run_sql(setup, q)[0][0]
    prompt = (
        f"Таблица `users`:\n\n{_table_md(['id', 'name'], users)}\n\n"
        f"Таблица `orders`:\n\n{_table_md(['id', 'user_id', 'amount'], orders)}\n\nКакое число вернёт запрос?"
    )
    return number(prompt, ans, code=q, code_lang="sql")


@family("sql.not_in_null", "sql", 5, "NOT IN и NULL в подзапросе")
def _(rng):
    a_vals = rng.sample(range(1, 12), rng.randint(5, 7))
    b_vals = rng.sample(a_vals, 2) + [rng.randint(20, 30)]
    with_null = rng.random() < 0.6
    rows_b = [(v,) for v in b_vals] + ([(None,)] if with_null else [])
    rng.shuffle(rows_b)
    setup = (
        "CREATE TABLE a (x INTEGER);\nCREATE TABLE b (x INTEGER);\n"
        + sql_insert("a", ["x"], [(v,) for v in a_vals])
        + "\n"
        + sql_insert("b", ["x"], rows_b)
    )
    q = rng.choice(
        [
            "SELECT COUNT(*) FROM a WHERE x NOT IN (SELECT x FROM b);",
            "SELECT COUNT(*) FROM a WHERE NOT EXISTS (SELECT 1 FROM b WHERE b.x = a.x);",
        ]
    )
    ans = run_sql(setup, q)[0][0]
    prompt = (
        f"Таблица `a`: x = {', '.join(map(str, a_vals))}.\n"
        f"Таблица `b`: x = {', '.join('NULL' if r[0] is None else str(r[0]) for r in rows_b)}.\n\nКакое число вернёт запрос?"
    )
    return number(prompt, ans, code=q, code_lang="sql")


@family("sql.window", "sql", 4, "Оконные функции")
def _(rng):
    setup, rows = _employees(rng, rng.randint(7, 9))
    fn = rng.choice(["ROW_NUMBER()", "RANK()", "DENSE_RANK()"])
    k = rng.choice([1, 2])
    q = (
        "SELECT COUNT(*) FROM (\n"
        f"  SELECT name, {fn} OVER (PARTITION BY dept ORDER BY salary DESC) AS r\n"
        "  FROM employees\n"
        f") t WHERE r <= {k};"
    )
    ans = run_sql(setup, q)[0][0]
    prompt = f"Таблица `employees`:\n\n{_table_md(['name', 'dept', 'salary', 'bonus'], rows)}\n\nКакое число вернёт запрос?"
    return number(prompt, ans, code=q, code_lang="sql")


@family("sql.recursive_cte", "sql", 5, "Рекурсивные CTE: обход иерархии")
def _(rng):
    n = rng.randint(7, 10)
    rows = [(1, None)]
    for i in range(2, n + 1):
        rows.append((i, rng.randint(1, i - 1)))
    root = rng.choice([r[0] for r in rows if any(x[1] == r[0] for x in rows)])
    setup = "CREATE TABLE org (id INTEGER, manager_id INTEGER);\n" + sql_insert(
        "org", ["id", "manager_id"], rows
    )
    q = (
        "WITH RECURSIVE sub(id) AS (\n"
        f"  SELECT id FROM org WHERE id = {root}\n"
        "  UNION ALL\n"
        "  SELECT o.id FROM org o JOIN sub s ON o.manager_id = s.id\n"
        ")\nSELECT COUNT(*) FROM sub;"
    )
    ans = run_sql(setup, q)[0][0]
    pairs = ", ".join(f"{i}→{m if m is not None else 'NULL'}" for i, m in rows)
    prompt = f"Таблица `org(id, manager_id)`: {pairs}.\n\nКакое число вернёт запрос?"
    return number(prompt, ans, code=q, code_lang="sql")


@family("sql.distinct_join", "sql", 4, "Размножение строк при JOIN")
def _(rng):
    cats = [(i + 1, c) for i, c in enumerate(rng.sample(CITIES, 3))]
    shops = [(i + 1, rng.choice(cats)[0]) for i in range(rng.randint(4, 6))]
    sales = [(rng.choice(shops)[0], rng.randrange(10, 100, 10)) for _ in range(rng.randint(6, 9))]
    setup = (
        "CREATE TABLE cities (id INTEGER, name TEXT);\nCREATE TABLE shops (id INTEGER, city_id INTEGER);\n"
        "CREATE TABLE sales (shop_id INTEGER, amount INTEGER);\n"
        + sql_insert("cities", ["id", "name"], cats)
        + "\n"
        + sql_insert("shops", ["id", "city_id"], shops)
        + "\n"
        + sql_insert("sales", ["shop_id", "amount"], sales)
    )
    city = rng.choice(cats)
    q = (
        "SELECT COUNT(*) FROM cities c\n"
        "JOIN shops s ON s.city_id = c.id\n"
        "JOIN sales x ON x.shop_id = s.id\n"
        f"WHERE c.name = '{city[1]}';"
    )
    ans = run_sql(setup, q)[0][0]
    prompt = (
        f"`cities(id, name)`: {', '.join(f'({a}, {b})' for a, b in cats)}\n\n"
        f"`shops(id, city_id)`: {', '.join(f'({a}, {b})' for a, b in shops)}\n\n"
        f"`sales(shop_id, amount)`: {', '.join(f'({a}, {b})' for a, b in sales)}\n\nКакое число вернёт запрос?"
    )
    return number(prompt, ans, code=q, code_lang="sql")


@family("sql.index", "sql", 3, "Индексы: какой индекс поможет запросу")
def _(rng):
    a, b, c = rng.sample(["user_id", "status", "created_at", "city", "category_id", "price"], 3)
    q = f"SELECT * FROM orders WHERE {a} = ? AND {b} > ? ORDER BY {b};"
    correct = f"Составной индекс ({a}, {b})"
    distractors = [
        f"Составной индекс ({b}, {a})",
        f"Индекс по ({c})",
        f"Отдельные индексы по {a} и по {b} — всегда лучше составного",
        "Индексы не влияют на такие запросы",
    ]
    return single(
        rng,
        "Какой индекс наиболее эффективен для запроса (равенство по первому столбцу, диапазон и сортировка по второму)?",
        correct,
        distractors,
        code=q,
        code_lang="sql",
    )


@family("sql.isolation", "sql", 4, "Уровни изоляции транзакций")
def _(rng):
    cases = [
        ("грязное чтение (dirty read)", "READ UNCOMMITTED"),
        ("неповторяющееся чтение (non-repeatable read)", "READ COMMITTED"),
        ("фантомное чтение (phantom read)", "REPEATABLE READ"),
    ]
    anomaly, weakest = rng.choice(cases)
    order_ = ["READ UNCOMMITTED", "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"]
    ans = order_[order_.index(weakest) + 1]
    prompt = f"По стандарту SQL, какой *минимальный* уровень изоляции гарантированно исключает аномалию «{anomaly}»?"
    return single(rng, prompt, ans, [o for o in order_ if o != ans])


@family("sql.normal_forms", "sql", 3, "Нормализация")
def _(rng):
    cases = [
        ("в столбце `phones` хранится строка «+7..., +7...» с несколькими телефонами", "1НФ"),
        (
            "в таблице `order_items(order_id, product_id, product_name, qty)` с ключом (order_id, product_id) имя товара зависит только от product_id",
            "2НФ",
        ),
        (
            "в таблице `employees(id, dept_id, dept_name)` название отдела зависит от dept_id, а не от id",
            "3НФ",
        ),
    ]
    situation, nf = rng.choice(cases)
    return single(
        rng,
        f"Какая нормальная форма нарушена: {situation}?",
        nf,
        ["1НФ", "2НФ", "3НФ", "НФБК", "Нарушений нет"],
    )
