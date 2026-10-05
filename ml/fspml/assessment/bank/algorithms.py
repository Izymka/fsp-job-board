"""Семейства заданий: алгоритмы и структуры данных (языконезависимые якоря)."""

from __future__ import annotations

import heapq
import math
import random
from collections import deque

from ..items import family, number, single, text
from ._util import run_py

COMPLEXITIES = ["O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n²)", "O(n³)", "O(2ⁿ)"]


@family("alg.binary_search", "algorithms", 1, "Бинарный поиск: число сравнений")
def _(rng):
    n = rng.choice([7, 15, 31, 63, 100, 127, 255, 500, 1000, 1023, 4095, 10**6])
    ans = math.ceil(math.log2(n + 1))
    prompt = (
        f"Отсортированный массив содержит {n:,} элементов".replace(",", " ")
        + ". Какое **максимальное** число сравнений с искомым значением сделает бинарный поиск "
        "(одно сравнение на шаг) в худшем случае?"
    )
    return number(prompt, ans)


@family("alg.complexity_loops", "algorithms", 1, "Сложность вложенных циклов")
def _(rng):
    shapes = [
        ("for i in range(n):\n    for j in range(n):\n        work()", "O(n²)"),
        ("for i in range(n):\n    for j in range({k}):\n        work()", "O(n)"),
        ("for i in range(n):\n    work()\nfor j in range(n):\n    work()", "O(n)"),
        ("for i in range(n):\n    for j in range(i):\n        work()", "O(n²)"),
        (
            "for i in range(n):\n    for j in range(n):\n        for k in range(n):\n            work()",
            "O(n³)",
        ),
        ("i = n\nwhile i > 1:\n    i //= {k}\n    work()", "O(log n)"),
    ]
    code, ans = rng.choice(shapes)
    code = code.replace("{k}", str(rng.randint(2, 9)))
    return single(
        rng,
        "Какова временная сложность фрагмента (work() — O(1))?",
        ans,
        [c for c in COMPLEXITIES if c != ans],
        code=code,
        code_lang="python",
    )


@family("alg.complexity_tricky", "algorithms", 3, "Сложность: неочевидные случаи")
def _(rng):
    k = rng.randint(2, 4)
    shapes = [
        (f"i = 1\nwhile i < n:\n    for j in range(n):\n        work()\n    i *= {k}", "O(n log n)"),
        (f"i = 1\nwhile i < n:\n    for j in range(i):\n        work()\n    i *= {k}", "O(n)"),
        ("for i in range(n):\n    j = 1\n    while j < n:\n        j *= 2\n        work()", "O(n log n)"),
        ("for i in range(1, n + 1):\n    for j in range(0, n, i):\n        work()", "O(n log n)"),
        ("def f(n):\n    if n <= 1:\n        return 1\n    return f(n - 1) + f(n - 1)", "O(2ⁿ)"),
    ]
    code, ans = rng.choice(shapes)
    return single(
        rng,
        "Какова временная сложность фрагмента (work() — O(1))?",
        ans,
        [c for c in COMPLEXITIES if c != ans],
        code=code,
        code_lang="python",
    )


@family("alg.stack_queue", "algorithms", 2, "Стек и очередь")
def _(rng):
    use_stack = rng.random() < 0.5
    ops = []
    pushed = 0
    size = 0
    for _ in range(rng.randint(7, 10)):
        if size > 0 and rng.random() < 0.4:
            ops.append("pop")
            size -= 1
        else:
            pushed += 1
            ops.append(f"push({pushed * rng.randint(1, 3)})")
            size += 1
    ds: deque[int] = deque()
    popped = []
    for op in ops:
        if op == "pop":
            popped.append(ds.pop() if use_stack else ds.popleft())
        else:
            ds.append(int(op[5:-1]))
    name = "стек (LIFO)" if use_stack else "очередь (FIFO)"
    prompt = (
        f"Над пустой структурой «{name}» выполнены операции:\n\n`{', '.join(ops)}`\n\n"
        "Какие значения будут извлечены операциями pop, по порядку? Введите через запятую. "
        "Если ни одного — введите `-`."
    )
    ans = ",".join(map(str, popped)) or "-"
    return text(prompt, ans, normalize="nospace")


@family("alg.bubble_pass", "algorithms", 2, "Сортировки: один проход")
def _(rng):
    xs = rng.sample(range(1, 50), rng.randint(6, 7))
    algo = rng.choice(["bubble", "insertion"])
    ys = xs[:]
    if algo == "bubble":
        for i in range(len(ys) - 1):
            if ys[i] > ys[i + 1]:
                ys[i], ys[i + 1] = ys[i + 1], ys[i]
        desc = "одного полного прохода пузырьковой сортировки (слева направо, по возрастанию)"
    else:
        steps = 3
        for i in range(1, steps + 1):
            key, j = ys[i], i - 1
            while j >= 0 and ys[j] > key:
                ys[j + 1] = ys[j]
                j -= 1
            ys[j + 1] = key
        desc = "трёх первых шагов сортировки вставками (элементы с индексами 1, 2, 3 вставлены в отсортированный префикс)"
    prompt = f"Массив `{xs}`. Каким он станет после {desc}? Введите элементы через запятую."
    return text(prompt, ",".join(map(str, ys)), normalize="nospace")


@family("alg.ds_choice", "algorithms", 2, "Выбор структуры данных")
def _(rng):
    cases = [
        ("быстро проверять, встречался ли уже идентификатор пользователя", "Хеш-множество (set)"),
        (
            "постоянно получать минимальный элемент из динамически пополняемого набора",
            "Двоичная куча (min-heap)",
        ),
        ("обрабатывать задачи строго в порядке поступления", "Очередь (FIFO)"),
        ("проверять сбалансированность скобок в выражении", "Стек"),
        ("искать все слова с заданным префиксом", "Префиксное дерево (trie)"),
        (
            "хранить отсортированные ключи и искать диапазоны за O(log n + k)",
            "Сбалансированное дерево поиска",
        ),
        (
            "объединять множества и проверять, лежат ли два элемента в одном",
            "Система непересекающихся множеств (DSU)",
        ),
    ]
    need, ans = rng.choice(cases)
    pool = [c[1] for c in cases if c[1] != ans] + ["Связный список"]
    return single(rng, f"Какую структуру данных лучше выбрать, если нужно {need}?", ans, pool)


def _random_graph(rng: random.Random, n: int, m: int, weighted: bool):
    edges = set()
    nodes = list(range(1, n + 1))
    # гарантируем связность: остовная цепочка
    perm = nodes[:]
    rng.shuffle(perm)
    for a, b in zip(perm, perm[1:]):
        edges.add((min(a, b), max(a, b)))
    while len(edges) < m:
        a, b = rng.sample(nodes, 2)
        edges.add((min(a, b), max(a, b)))
    return sorted((a, b, rng.randint(1, 9) if weighted else 1) for a, b in edges)


@family("alg.bfs", "algorithms", 3, "Кратчайший путь в невзвешенном графе")
def _(rng):
    n = rng.randint(6, 8)
    edges = _random_graph(rng, n, n + rng.randint(0, 2), weighted=False)
    adj = {i: [] for i in range(1, n + 1)}
    for a, b, _w in edges:
        adj[a].append(b)
        adj[b].append(a)
    s, t = rng.sample(range(1, n + 1), 2)
    dist = {s: 0}
    q = deque([s])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    prompt = (
        f"Неориентированный граф задан рёбрами: {', '.join(f'{a}–{b}' for a, b, _ in edges)}.\n\n"
        f"Какое минимальное число рёбер в пути из вершины {s} в вершину {t}?"
    )
    return number(prompt, dist[t])


@family("alg.dijkstra", "algorithms", 4, "Кратчайший путь во взвешенном графе")
def _(rng):
    n = rng.randint(5, 7)
    edges = _random_graph(rng, n, n + rng.randint(1, 3), weighted=True)
    adj = {i: [] for i in range(1, n + 1)}
    for a, b, w in edges:
        adj[a].append((b, w))
        adj[b].append((a, w))
    s, t = rng.sample(range(1, n + 1), 2)
    dist = {s: 0}
    pq = [(0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, math.inf):
            continue
        for v, w in adj[u]:
            if d + w < dist.get(v, math.inf):
                dist[v] = d + w
                heapq.heappush(pq, (d + w, v))
    prompt = (
        "Неориентированный взвешенный граф (ребро: вес): "
        + ", ".join(f"{a}–{b}: {w}" for a, b, w in edges)
        + f".\n\nЧему равна длина кратчайшего пути из {s} в {t}?"
    )
    return number(prompt, dist[t])


@family("alg.lis", "algorithms", 4, "Динамическое программирование: НВП")
def _(rng):
    xs = [rng.randint(1, 30) for _ in range(rng.randint(8, 10))]
    dp = [1] * len(xs)
    for i in range(len(xs)):
        for j in range(i):
            if xs[j] < xs[i]:
                dp[i] = max(dp[i], dp[j] + 1)
    prompt = f"Найдите длину наибольшей строго возрастающей подпоследовательности массива `{xs}`."
    return number(prompt, max(dp))


@family("alg.coins", "algorithms", 4, "ДП: размен монет (жадный не работает)")
def _(rng):
    coin_sets = [[1, 3, 4], [1, 5, 6, 9], [1, 4, 6], [1, 7, 10], [1, 6, 9, 10]]
    coins = rng.choice(coin_sets)
    target = rng.randint(11, 30)
    inf = 10**9
    dp = [0] + [inf] * target
    for x in range(1, target + 1):
        for c in coins:
            if c <= x:
                dp[x] = min(dp[x], dp[x - c] + 1)
    prompt = f"Монеты номиналов {coins} (каждого — сколько угодно). Какое минимальное число монет нужно, чтобы набрать ровно {target}?"
    return number(prompt, dp[target])


@family("alg.knapsack", "algorithms", 5, "ДП: рюкзак 0/1")
def _(rng):
    items = [(rng.randint(1, 6), rng.randint(2, 15)) for _ in range(5)]
    cap = rng.randint(8, 12)
    dp = [0] * (cap + 1)
    for w, v in items:
        for c in range(cap, w - 1, -1):
            dp[c] = max(dp[c], dp[c - w] + v)
    prompt = (
        f"Рюкзак вместимостью {cap}. Предметы (вес, ценность): {items}. Каждый предмет можно взять не более одного раза. "
        "Какова максимальная суммарная ценность?"
    )
    return number(prompt, dp[cap])


@family("alg.amortized", "algorithms", 5, "Амортизированный анализ динамического массива")
def _(rng):
    start = rng.choice([1, 2, 4])
    factor = rng.choice([2, 3])
    n = rng.randint(20, 60)
    code = (
        f"cap, size, copies = {start}, 0, 0\n"
        f"for _ in range({n}):\n"
        "    if size == cap:\n"
        "        copies += size\n"
        f"        cap *= {factor}\n"
        "    size += 1\n"
        "print(copies)"
    )
    ans = int(run_py(code))
    prompt = (
        f"Динамический массив начинается с ёмкости {start}; при заполнении ёмкость умножается на {factor}, "
        f"а все элементы копируются в новый буфер. Сколько всего копирований элементов произойдёт при {n} вставках в пустой массив?"
    )
    return number(prompt, ans)


@family("alg.hash_collisions", "algorithms", 3, "Хеш-таблица с открытой адресацией")
def _(rng):
    m = rng.choice([7, 11, 13])
    keys = rng.sample(range(10, 99), 5)
    table = [None] * m
    probes_total = 0
    for k in keys:
        h = k % m
        probes = 1
        while table[h] is not None:
            h = (h + 1) % m
            probes += 1
        table[h] = k
        probes_total += probes
    last = keys[-1]
    pos = table.index(last)
    prompt = (
        f"Хеш-таблица размера {m}, h(k) = k mod {m}, линейное пробирование (+1). "
        f"Ключи вставляются по порядку: {keys}. В какую ячейку (индекс от 0) попадёт ключ {last}?"
    )
    return number(prompt, pos)


@family("alg.recursion_calls", "algorithms", 2, "Рекурсия: число вызовов")
def _(rng):
    n = rng.randint(4, 7)
    kind = rng.choice(["fib", "linear"])
    if kind == "fib":
        code = (
            "calls = 0\ndef f(n):\n    global calls\n    calls += 1\n    if n < 2:\n        return n\n    return f(n - 1) + f(n - 2)\n"
            + f"f({n})\nprint(calls)"
        )
    else:
        code = (
            "calls = 0\ndef f(n):\n    global calls\n    calls += 1\n    if n == 0:\n        return 0\n    return n + f(n - 1)\n"
            + f"f({n})\nprint(calls)"
        )
    return number(
        "Сколько раз будет вызвана функция f (включая первый вызов)?",
        int(run_py(code)),
        code=code,
        code_lang="python",
    )


@family("alg.two_pointers", "algorithms", 3, "Два указателя / скользящее окно")
def _(rng):
    xs = [rng.randint(1, 9) for _ in range(rng.randint(8, 11))]
    s = rng.randint(10, 18)
    best = 0
    lo = cur = 0
    for hi, x in enumerate(xs):
        cur += x
        while cur > s:
            cur -= xs[lo]
            lo += 1
        best = max(best, hi - lo + 1)
    prompt = f"Массив `{xs}`. Какова максимальная длина непрерывного подмассива с суммой не больше {s}?"
    return number(prompt, best)
