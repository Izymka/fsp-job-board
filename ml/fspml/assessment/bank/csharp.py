"""Семейства заданий: C# / .NET.

Код — программа с top-level statements (C# 10+). Ответ вычисляется Python-моделью семантики C#;
тест `test_lang_families_match_runtime` запускает программу через `dotnet run` и сверяет вывод.
"""

from __future__ import annotations

from ..items import family, number, text
from ._util import WORDS

PREDICT = "Что выведет программа? Если строк несколько — введите их через пробел."


def cs_program(body: str, usings: tuple[str, ...] = ("System",), types: str = "") -> str:
    head = "".join(f"using {u};\n" for u in usings)
    tail = f"\n\n{types.strip(chr(10))}" if types else ""
    return f"{head}\n{body.strip(chr(10))}{tail}"


def cs_item(answer, code: str, prompt: str = PREDICT, normalize: str = "ci"):
    if isinstance(answer, int):
        item = number(prompt, answer, code=code, code_lang="csharp")
    else:
        item = text(prompt, answer, normalize=normalize, code=code, code_lang="csharp")
    item.explanation = "csharp"  # маркер для сверки с настоящим .NET в тестах
    return item


def cs_bool(x: bool) -> str:
    return "True" if x else "False"


@family("cs.int_division", "csharp", 1, "Целочисленное деление и остаток")
def _(rng):
    a, b = rng.randint(20, 99), rng.randint(3, 9)
    body = f'int a = {a};\nint b = {b};\nConsole.WriteLine($"{{a / b}} {{a % b}}");'
    return cs_item(f"{a // b} {a % b}", cs_program(body))


@family("cs.foreach_sum", "csharp", 1, "foreach и continue")
def _(rng):
    xs = rng.sample(range(1, 40), rng.randint(5, 8))
    m = rng.randint(2, 4)
    r = rng.randint(0, m - 1)
    body = (
        f"int[] xs = {{ {', '.join(map(str, xs))} }};\n"
        "int total = 0;\n"
        "foreach (int x in xs)\n{\n"
        f"    if (x % {m} == {r}) continue;\n"
        "    total += x;\n}\n"
        "Console.WriteLine(total);"
    )
    return cs_item(sum(x for x in xs if x % m != r), cs_program(body))


@family("cs.nullable", "csharp", 2, "Nullable, ?. и ??")
def _(rng):
    name = rng.choice(WORDS) if rng.random() < 0.5 else None
    count = rng.randint(1, 9) if rng.random() < 0.5 else None
    d = rng.randint(10, 20)
    body = (
        f"string? name = {f'{chr(34)}{name}{chr(34)}' if name else 'null'};\n"
        f"int? count = {count if count is not None else 'null'};\n"
        f'Console.WriteLine($"{{name?.Length ?? -1}} {{(count ?? {d}) * 2}}");'
    )
    ans = f"{len(name) if name else -1} {(count if count is not None else d) * 2}"
    return cs_item(ans, cs_program(body))


@family("cs.strings", "csharp", 2, "Неизменяемость string и StringBuilder")
def _(rng):
    w, t, t2 = rng.choice(WORDS), rng.choice(["Go", "Up", "Ok", "Net"]), rng.choice(["_v2", "_x", "_new"])
    noops = ["s.ToUpper();", f's.Replace("{w[0]}", "#");']
    rng.shuffle(noops)
    lines = [f'string s = "{w}";', *noops, "var sb = new StringBuilder(s);", f'sb.Append("{t}");']
    s, sb = w, w + t
    if rng.random() < 0.5:
        lines.append(f'sb.Insert(0, "{t2}");')
        sb = t2 + sb
    if rng.random() < 0.5:
        lines.append(f's += "{t2}";')
        s += t2
    lines.append('Console.WriteLine($"{s} {sb}");')
    return cs_item(f"{s} {sb}", cs_program("\n".join(lines), ("System", "System.Text")), normalize="exact")


_TYPE_PAIRS = [("Point", "Size"), ("Box", "Slot"), ("Cell", "Node"), ("Money", "Price")]


@family("cs.value_reference", "csharp", 3, "struct и class: копирование значения и ссылки")
def _(rng):
    t1, t2 = rng.choice(_TYPE_PAIRS)
    k1, k2 = rng.choice([("struct", "class"), ("class", "struct"), ("struct", "struct"), ("class", "class")])
    a1, b1, a2, b2 = rng.sample(range(1, 99), 4)
    body = (
        f"var p = new {t1} {{ Value = {a1} }};\nvar q = p;\nq.Value = {b1};\n\n"
        f"var r = new {t2} {{ Value = {a2} }};\nvar s = r;\ns.Value = {b2};\n\n"
        'Console.WriteLine($"{p.Value} {r.Value}");'
    )
    types = f"{k1} {t1} {{ public int Value; }}\n{k2} {t2} {{ public int Value; }}"
    ans = f"{a1 if k1 == 'struct' else b1} {a2 if k2 == 'struct' else b2}"
    return cs_item(ans, cs_program(body, types=types))


@family("cs.equality", "csharp", 3, "== и Equals: упаковка, строки, ссылки")
def _(rng):
    w = rng.choice(WORDS)
    pool = [
        ("a == b", False),
        ("a.Equals(b)", True),
        ("(int)a == (int)b", True),
        ("s1 == s2", True),
        ("o1 == o2", False),
        ("o1.Equals(o2)", True),
        ("object.ReferenceEquals(s1, s2)", False),
    ]
    picked = rng.sample(pool, 3)
    v = rng.randint(1, 500)
    body = (
        f"object a = {v};\nobject b = {v};\n"
        f'string s1 = "{w}";\nstring s2 = new string(s1.ToCharArray());\n'
        "object o1 = s1;\nobject o2 = s2;\n"
        'Console.WriteLine($"' + " ".join(f"{{{e}}}" for e, _ in picked) + '");'
    )
    return cs_item(" ".join(cs_bool(t) for _, t in picked), cs_program(body))


@family("cs.ref_out", "csharp", 3, "Параметры ref и out")
def _(rng):
    a, b, k = rng.randint(1, 30), rng.randint(1, 30), rng.randint(2, 9)
    body = (
        f"int a = {a};\nint b = {b};\nUpdate(a, ref b, out int c);\n"
        'Console.WriteLine($"{a} {b} {c}");\n\n'
        "void Update(int x, ref int y, out int z)\n{\n"
        f"    x += {k};\n    y += {k};\n    z = x + y;\n}}"
    )
    return cs_item(f"{a} {b + k} {a + b + 2 * k}", cs_program(body))


@family("cs.linq_deferred", "csharp", 4, "Отложенное выполнение LINQ")
def _(rng):
    xs = rng.sample(range(1, 50), rng.randint(5, 7))
    t = rng.choice(sorted(xs)[1:-1])
    added = rng.sample([v for v in range(1, 99) if v not in xs], 2)
    materialize = rng.random() < 0.4
    body = (
        f"var xs = new List<int> {{ {', '.join(map(str, xs))} }};\n"
        f"var query = xs.Where(x => x > {t}){'.ToList()' if materialize else ''};\n"
        f"xs.Add({added[0]});\nxs.Add({added[1]});\n"
        'Console.WriteLine($"{query.Count()} {query.Sum()}");'
    )
    src = xs if materialize else xs + added
    sel = [x for x in src if x > t]
    return cs_item(
        f"{len(sel)} {sum(sel)}", cs_program(body, ("System", "System.Collections.Generic", "System.Linq"))
    )


@family("cs.closures", "csharp", 4, "Замыкания в for и foreach")
def _(rng):
    n, k = rng.randint(3, 6), rng.randint(2, 9)
    j = rng.randint(0, n - 2)
    form = rng.choice(["for", "foreach", "copy"])
    if form == "for":
        loop = f"for (int i = 0; i < {n}; i++)\n{{\n    actions.Add(() => i * {k});\n}}"
        ans = n * k
    elif form == "foreach":
        loop = f"foreach (int i in Enumerable.Range(0, {n}))\n{{\n    actions.Add(() => i * {k});\n}}"
        ans = j * k
    else:
        loop = f"for (int i = 0; i < {n}; i++)\n{{\n    int copy = i;\n    actions.Add(() => copy * {k});\n}}"
        ans = j * k
    body = f"var actions = new List<Func<int>>();\n{loop}\nConsole.WriteLine(actions[{j}]());"
    return cs_item(ans, cs_program(body, ("System", "System.Collections.Generic", "System.Linq")))


@family("cs.exceptions", "csharp", 4, "try / catch / finally: порядок выполнения")
def _(rng):
    limit = rng.randint(10, 30)
    a, b = rng.randint(1, limit), rng.randint(limit + 1, limit + 20)
    if rng.random() < 0.5:
        a, b = b, a
    if rng.random() < 0.3:
        b = rng.randint(1, limit)
    body = (
        f"int r1 = Run({a});\nint r2 = Run({b});\n"
        'Console.WriteLine($" {r1 + r2}");\n\n'
        "int Run(int x)\n{\n"
        '    try\n    {\n        Console.Write("T");\n'
        f"        if (x > {limit}) throw new InvalidOperationException();\n"
        "        return x;\n    }\n"
        '    catch (InvalidOperationException)\n    {\n        Console.Write("C");\n        return -1;\n    }\n'
        '    finally\n    {\n        Console.Write("F");\n    }\n}'
    )

    def run(x):
        return ("TCF", -1) if x > limit else ("TF", x)

    (o1, r1), (o2, r2) = run(a), run(b)
    prompt = "Что выведет программа? `Console.Write` печатает без перевода строки."
    return cs_item(f"{o1}{o2} {r1 + r2}", cs_program(body), prompt=prompt)


@family("cs.iterators", "csharp", 5, "yield return: ленивость и повторное перечисление")
def _(rng):
    n, k = rng.randint(5, 9), rng.randint(2, 6)
    t = rng.randint(k, k * (n - 1) - 1)
    recount = rng.random() < 0.5
    body = (
        "int produced = 0;\n\n"
        "IEnumerable<int> Numbers()\n{\n"
        f"    for (int i = 1; i <= {n}; i++)\n    {{\n        produced++;\n        yield return i * {k};\n    }}\n}}\n\n"
        "var seq = Numbers();\n"
        f"int first = seq.First(x => x > {t});\n"
        + ("int count = seq.Count();\n" if recount else "")
        + 'Console.WriteLine($"{first} {produced}");'
    )
    i_first = next(i for i in range(1, n + 1) if i * k > t)
    produced = i_first + (n if recount else 0)
    return cs_item(
        f"{i_first * k} {produced}", cs_program(body, ("System", "System.Collections.Generic", "System.Linq"))
    )
