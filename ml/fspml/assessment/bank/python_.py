"""Семейства заданий: Python. Ответы вычисляются исполнением сгенерированного сниппета."""

from __future__ import annotations

import random

from ..items import family, number, single, text
from ._util import NAMES, WORDS, fmt_list, run_py

PREDICT = "Что выведет программа? Введите вывод точно так, как его напечатает Python."


@family("py.index", "python", 1, "Индексация списков и строк")
def _(rng: random.Random):
    xs = rng.sample(range(1, 60), rng.randint(5, 8))
    i = rng.randint(1, len(xs) - 1)
    j = -rng.randint(1, len(xs) - 1)
    w = rng.choice(WORDS)
    k = rng.randint(0, len(w) - 1)
    code = f"xs = {fmt_list(xs)}\nword = {w!r}\nprint(xs[{i}] + xs[{j}], word[{k}])"
    return text(PREDICT, run_py(code), normalize="ci", code=code, code_lang="python")


@family("py.divmod", "python", 1, "Целочисленное деление и остаток")
def _(rng):
    a, b = rng.randint(10, 99), rng.randint(3, 9)
    code = f"a, b = {a}, {b}\nprint(a // b, a % b)"
    return text(PREDICT, run_py(code), normalize="ci", code=code, code_lang="python")


@family("py.divmod_neg", "python", 3, "Деление с отрицательными числами")
def _(rng):
    a, b = -rng.randint(7, 60), rng.randint(3, 9)
    while a % b == 0:
        a -= 1
    code = f"print({a} // {b}, {a} % {b}, int({a} / {b}))"
    return text(PREDICT, run_py(code), normalize="ci", code=code, code_lang="python")


@family("py.slice", "python", 2, "Срезы с шагом")
def _(rng):
    n = rng.randint(7, 10)
    xs = list(range(rng.randint(0, 5), rng.randint(0, 5) + n))
    start, stop = rng.randint(0, 3), rng.randint(-3, -1)
    step = rng.choice([2, 3])
    variant = rng.random() < 0.3
    expr = f"xs[::-{step}]" if variant else f"xs[{start}:{stop}:{step}]"
    code = f"xs = {fmt_list(xs)}\nprint({expr})"
    return text(PREDICT, run_py(code), code=code, code_lang="python")


@family("py.comprehension", "python", 2, "Списковые включения с условием")
def _(rng):
    n, k, m = rng.randint(8, 15), rng.randint(2, 5), rng.randint(2, 4)
    form = rng.choice(["list", "sum", "len"])
    comp = f"[x * {k} for x in range({n}) if x % {m} == 0]"
    expr = {"list": comp, "sum": f"sum({comp})", "len": f"len({comp})"}[form]
    code = f"print({expr})"
    return text(PREDICT, run_py(code), code=code, code_lang="python")


@family("py.dict", "python", 2, "Словари: get, setdefault, update")
def _(rng):
    keys = rng.sample(NAMES, 4)
    d = {keys[0]: rng.randint(1, 9), keys[1]: rng.randint(1, 9)}
    v = rng.randint(10, 20)
    code = (
        f"d = {d!r}\n"
        f"d.setdefault({keys[0]!r}, {v})\n"
        f"d.setdefault({keys[2]!r}, {v})\n"
        f"d.update({{{keys[1]!r}: {v + 1}}})\n"
        f"print(d.get({keys[3]!r}, 0) + sum(d.values()))"
    )
    return text(PREDICT, run_py(code), code=code, code_lang="python")


@family("py.loop_control", "python", 2, "break / continue / else у цикла")
def _(rng):
    n, skip, stop = rng.randint(8, 14), rng.randint(2, 4), rng.randint(4, 7)
    use_break = rng.random() < 0.6
    stop_line = f"    if i == {stop}:\n        break\n" if use_break else ""
    code = (
        "total = 0\n"
        f"for i in range({n}):\n"
        f"    if i % {skip} == 0:\n        continue\n"
        f"{stop_line}"
        "    total += i\n"
        "else:\n    total += 100\n"
        "print(total)"
    )
    ans = run_py(code)
    return number(PREDICT, int(ans), code=code, code_lang="python")


@family("py.aliasing", "python", 3, "Ссылки, копии и изменяемость")
def _(rng):
    xs = rng.sample(range(1, 20), rng.randint(2, 5))
    copy_kind = rng.choice(["a[:]", "list(a)", "a.copy()"])
    nb, nc = rng.randint(1, 3), rng.randint(0, 2)
    rebind = rng.choice(["a = a + [0]", "a += [0]", "a = [0]"])
    code = (
        f"a = {fmt_list(xs)}\n"
        "b = a\n"
        f"c = {copy_kind}\n"
        + "".join(f"b.append({rng.randint(20, 40)})\n" for _ in range(nb))
        + "".join(f"c.append({rng.randint(40, 60)})\n" for _ in range(nc))
        + f"{rebind}\n"
        "print(len(a), len(b), len(c))"
    )
    return text(PREDICT, run_py(code), normalize="ci", code=code, code_lang="python")


@family("py.mutable_default", "python", 3, "Изменяемое значение по умолчанию")
def _(rng):
    calls = rng.randint(2, 4)
    vals = rng.sample(range(1, 9), calls)
    name = rng.choice(["acc", "items", "bag", "seen"])
    lines = [f"def add(x, {name}=[]):", f"    {name}.append(x)", f"    return {name}", ""]
    for v in vals[:-1]:
        lines.append(f"add({v})")
    lines.append(f"print(add({vals[-1]}))")
    code = "\n".join(lines)
    return text(PREDICT, run_py(code), code=code, code_lang="python")


@family("py.late_binding", "python", 3, "Замыкания и позднее связывание")
def _(rng):
    n, k = rng.randint(3, 6), rng.randint(2, 9)
    j = rng.randint(0, n - 1)
    fix = rng.random() < 0.35
    lam = f"lambda i=i: i * {k}" if fix else f"lambda: i * {k}"
    code = f"fs = [{lam} for i in range({n})]\nprint(fs[{j}]())"
    return number(PREDICT, int(run_py(code)), code=code, code_lang="python")


@family("py.generator", "python", 3, "Генераторы и ленивые вычисления")
def _(rng):
    n, k = rng.randint(4, 7), rng.randint(1, 3)
    code = (
        "def gen(n):\n"
        "    for i in range(n):\n"
        "        yield i * i\n\n"
        f"g = gen({n})\n" + "".join("next(g)\n" for _ in range(k)) + "print(sum(g))"
    )
    return number(PREDICT, int(run_py(code)), code=code, code_lang="python")


@family("py.scope", "python", 4, "Области видимости: global / nonlocal")
def _(rng):
    start, inc, calls = rng.randint(0, 5), rng.randint(2, 5), rng.randint(2, 4)
    use_nonlocal = rng.random() < 0.5
    if use_nonlocal:
        code = (
            "def make():\n"
            f"    count = {start}\n"
            "    def inc():\n"
            "        nonlocal count\n"
            f"        count += {inc}\n"
            "        return count\n"
            "    return inc\n\n"
            "f = make()\n" + "".join("f()\n" for _ in range(calls - 1)) + "print(f())"
        )
    else:
        code = (
            f"x = {start}\n"
            "def outer():\n"
            f"    x = {start + 100}\n"
            "    def inner():\n"
            "        global x\n"
            f"        x += {inc}\n"
            "    for _ in range(" + str(calls) + "):\n"
            "        inner()\n"
            "    return x\n\n"
            "print(outer(), x)"
        )
    return text(PREDICT, run_py(code), normalize="ci", code=code, code_lang="python")


@family("py.finally", "python", 4, "try / except / else / finally")
def _(rng):
    raise_it = rng.random() < 0.5
    ret_in_finally = rng.random() < 0.4
    a, b, c, d = rng.sample(range(1, 50), 4)
    code = (
        "def f():\n"
        "    log = []\n"
        "    try:\n"
        + (
            f"        log.append({a})\n        raise ValueError\n"
            if raise_it
            else f"        log.append({a})\n"
        )
        + "    except ValueError:\n"
        f"        log.append({b})\n"
        "        return log\n"
        "    else:\n"
        f"        log.append({c})\n"
        "    finally:\n"
        f"        log.append({d})\n"
        + ("        return log[:1]\n" if ret_in_finally else "")
        + "    return log\n\n"
        "print(f())"
    )
    return text(PREDICT, run_py(code), code=code, code_lang="python")


@family("py.mro", "python", 4, "Множественное наследование и MRO")
def _(rng):
    names = rng.sample(["A", "B", "C", "D", "E", "K", "M", "P"], 4)
    base, left, right, child = names
    overrides = rng.sample([left, right, base], rng.randint(1, 2))
    lines = [f"class {base}:", f"    def who(self): return {base!r}", ""]
    for cls in (left, right):
        lines.append(f"class {cls}({base}):")
        lines.append(f"    def who(self): return {cls!r} + super().who()" if cls in overrides else "    pass")
        lines.append("")
    lines += [f"class {child}({left}, {right}):", "    pass", "", f"print({child}().who())"]
    code = "\n".join(lines)
    return text(PREDICT, run_py(code), code=code, code_lang="python")


@family("py.hash_eq", "python", 5, "__eq__ / __hash__ и множества")
def _(rng):
    vals = [rng.randint(1, 4) for _ in range(rng.randint(5, 7))]
    mod = rng.choice([2, 3])
    code = (
        "class Key:\n"
        "    def __init__(self, v):\n"
        "        self.v = v\n"
        "    def __eq__(self, other):\n"
        f"        return self.v % {mod} == other.v % {mod}\n"
        "    def __hash__(self):\n"
        f"        return self.v % {mod}\n\n"
        f"keys = [Key(v) for v in {fmt_list(vals)}]\n"
        "print(len(set(keys)), len(set(k.v for k in keys)))"
    )
    return text(PREDICT, run_py(code), normalize="ci", code=code, code_lang="python")


@family("py.asyncio_order", "python", 5, "Порядок выполнения корутин asyncio")
def _(rng):
    letters = rng.sample("ABCDEFGHKMNPRSTX", 3)
    sleeps = rng.sample([0, 0.01, 0.02], 3)
    code = (
        "import asyncio\n\n"
        "out = []\n\n"
        "async def worker(name, delay):\n"
        "    out.append(name.lower())\n"
        "    await asyncio.sleep(delay)\n"
        "    out.append(name)\n\n"
        "async def main():\n"
        "    await asyncio.gather("
        + ", ".join(f"worker({ch!r}, {s})" for ch, s in zip(letters, sleeps))
        + ")\n"
        "    print(''.join(out))\n\n"
        "asyncio.run(main())"
    )
    return text(PREDICT, run_py(code), normalize="exact", code=code, code_lang="python")


@family("py.complexity_builtin", "python", 2, "Сложность операций встроенных типов")
def _(rng):
    cases = [
        ("проверка `x in s`, где `s` — set из n элементов", "O(1) в среднем"),
        ("проверка `x in xs`, где `xs` — list из n элементов", "O(n)"),
        ("`xs.append(x)` для list", "O(1) амортизированно"),
        ("`xs.insert(0, x)` для list из n элементов", "O(n)"),
        ("`d[k]` для dict из n элементов", "O(1) в среднем"),
        ("`sorted(xs)` для list из n элементов", "O(n log n)"),
        ("`xs.pop()` (последний элемент) для list", "O(1) амортизированно"),
        ("`dq.appendleft(x)` для collections.deque", "O(1)"),
    ]
    q, ans = rng.choice(cases)
    pool = ["O(1) в среднем", "O(n)", "O(1) амортизированно", "O(n log n)", "O(log n)", "O(1)", "O(n²)"]
    pool = [p for p in pool if p != ans and not (p.startswith("O(1)") and ans.startswith("O(1)"))]
    return single(rng, f"Какова временная сложность операции: {q}?", ans, pool)


@family("py.sort_key", "python", 3, "Сортировка по ключу и стабильность")
def _(rng):
    people = [(n.capitalize(), rng.randint(20, 23)) for n in rng.sample(NAMES, 5)]
    reverse = rng.random() < 0.4
    code = (
        f"people = {people!r}\n"
        f"people.sort(key=lambda p: p[1]{', reverse=True' if reverse else ''})\n"
        "print(','.join(p[0] for p in people))"
    )
    return text(PREDICT, run_py(code), normalize="ci", code=code, code_lang="python")


@family("py.str_ops", "python", 2, "Операции над строками")
def _(rng):
    w = rng.choice(WORDS)
    k = rng.randint(2, 3)
    sep = rng.choice(["-", "+", "."])
    code = (
        f"s = {w!r}\n"
        f"t = s * {k}\n"
        f"parts = t.split({w[0]!r})\n"
        f"print(len(parts), {sep!r}.join(p.upper() for p in parts if p)[:{rng.randint(5, 9)}])"
    )
    return text(PREDICT, run_py(code), normalize="ci", code=code, code_lang="python")
