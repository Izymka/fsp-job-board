"""Семейства заданий: Java.

В бэкенде нет JVM, поэтому ответ вычисляется Python-моделью семантики Java. Код задания — полная
программа (класс Main), тест `test_lang_families_match_runtime` запускает её настоящей JVM и сверяет вывод.
"""

from __future__ import annotations

import textwrap

from ..items import family, text
from ._util import NAMES, WORDS

PREDICT = "Что выведет программа? Если строк несколько — введите их через пробел."
INT_MAX = 2**31 - 1


def java_main(body: str, members: str = "", imports: str = "") -> str:
    head = f"{imports}\n\n" if imports else ""
    mem = textwrap.indent(members.strip("\n"), "    ") + "\n\n" if members else ""
    return (
        f"{head}public class Main {{\n{mem}"
        "    public static void main(String[] args) {\n"
        f"{textwrap.indent(body.strip(chr(10)), ' ' * 8)}\n"
        "    }\n}"
    )


def java_text(answer, code: str, prompt: str = PREDICT, normalize: str = "ci"):
    item = text(prompt, str(answer), normalize=normalize, code=code, code_lang="java")
    item.explanation = "java"  # маркер для сверки с настоящей JVM в тестах
    return item


def wrap32(x: int) -> int:
    return (x + 2**31) % 2**32 - 2**31


@family("java.int_division", "java", 1, "Целочисленное деление и остаток")
def _(rng):
    a, b = rng.randint(20, 99), rng.randint(3, 9)
    body = f'int a = {a};\nint b = {b};\nSystem.out.println(a / b + " " + a % b);'
    return java_text(f"{a // b} {a % b}", java_main(body))


@family("java.loop_sum", "java", 1, "Цикл for с шагом и continue")
def _(rng):
    a, b, s = rng.randint(0, 5), rng.randint(14, 30), rng.randint(2, 4)
    m = rng.randint(3, 5)
    r = rng.randint(0, m - 1)
    acc = rng.choice(["total", "sum", "acc"])
    body = (
        f"int {acc} = 0;\n"
        f"for (int i = {a}; i < {b}; i += {s}) {{\n"
        f"    if (i % {m} == {r}) {{\n        continue;\n    }}\n"
        f"    {acc} += i;\n}}\n"
        f"System.out.println({acc});"
    )
    return java_text(sum(i for i in range(a, b, s) if i % m != r), java_main(body))


@family("java.string_equality", "java", 2, "Сравнение строк: == и equals")
def _(rng):
    w = rng.choice(WORDS)
    k = rng.randint(1, len(w) - 1)
    exprs = {
        "literal": (f'"{w}"', True),
        "new": (f'new String("{w}")', False),
        "intern": (f'new String("{w}").intern()', True),
        "constant": (f'"{w[:k]}" + "{w[k:]}"', True),
        "builder": (f'new StringBuilder("{w}").toString()', False),
        "value_of": ("String.valueOf(a)", True),
    }
    kb, kc = rng.sample(sorted(exprs), 2)
    (eb, tb), (ec, tc) = exprs[kb], exprs[kc]
    body = (
        f'String a = "{w}";\nString b = {eb};\nString c = {ec};\n'
        'System.out.println((a == b) + " " + (a == c) + " " + b.equals(c));'
    )
    return java_text(f"{str(tb).lower()} {str(tc).lower()} true", java_main(body))


@family("java.string_builder", "java", 2, "Неизменяемость String и StringBuilder")
def _(rng):
    w, t, t2 = rng.choice(WORDS), rng.choice(["Go", "Up", "Ok", "Js"]), rng.choice(["_v2", "_x", "_new"])
    noops = [f's.concat("{t}");', "s.toUpperCase();"]
    rng.shuffle(noops)
    lines = [
        f'String s = "{w}";',
        f'StringBuilder sb = new StringBuilder("{w}");',
        *noops,
        f'sb.append("{t}");',
    ]
    s, sb = w, w + t
    if rng.random() < 0.5:
        lines.append("sb.reverse();")
        sb = sb[::-1]
    if rng.random() < 0.5:
        lines.append(f's = s.concat("{t2}");')
        s += t2
    lines.append('System.out.println(s + " " + sb);')
    return java_text(f"{s} {sb}", java_main("\n".join(lines)), normalize="exact")


@family("java.hashmap_merge", "java", 2, "HashMap: merge и getOrDefault")
def _(rng):
    keys = rng.sample(NAMES, rng.randint(3, 4))
    words = [rng.choice(keys) for _ in range(rng.randint(6, 9))]
    present = sorted(set(words))
    q = rng.choice(present)
    z = rng.choice([w for w in NAMES if w not in present]) if rng.random() < 0.5 else rng.choice(present)
    arr = ", ".join(f'"{w}"' for w in words)
    body = (
        f"String[] words = {{{arr}}};\n"
        "Map<String, Integer> counts = new HashMap<>();\n"
        "for (String w : words) {\n    counts.merge(w, 1, Integer::sum);\n}\n"
        f'System.out.println(counts.get("{q}") + " " + counts.getOrDefault("{z}", 0) + " " + counts.size());'
    )
    ans = f"{words.count(q)} {words.count(z)} {len(present)}"
    return java_text(ans, java_main(body, imports="import java.util.*;"))


@family("java.pass_by_value", "java", 3, "Передача аргументов: значения и ссылки на массивы")
def _(rng):
    a, b, k = rng.randint(1, 30), rng.randint(1, 30), rng.randint(2, 9)
    members = (
        "static void update(int[] arr, int n) {\n"
        "    arr[0] += n;\n"
        "    n *= 2;\n"
        "    arr = new int[] { 0, 0 };\n"
        "    arr[1] = n;\n"
        "}"
    )
    body = (
        f"int[] data = {{ {a}, {b} }};\nint n = {k};\nupdate(data, n);\n"
        'System.out.println(data[0] + " " + data[1] + " " + n);'
    )
    return java_text(f"{a + k} {b} {k}", java_main(body, members))


@family("java.integer_cache", "java", 3, "Автоупаковка и кэш Integer")
def _(rng):
    def value():
        return rng.choice([rng.randint(-128, 127), rng.randint(128, 2000), -rng.randint(129, 1000)])

    p, q = value(), value()
    body = (
        f"Integer a = {p}, b = {p};\nInteger c = {q}, d = {q};\n"
        'System.out.println((a == b) + " " + (c == d) + " " + c.equals(d));'
    )
    cached = lambda v: -128 <= v <= 127  # noqa: E731
    return java_text(f"{str(cached(p)).lower()} {str(cached(q)).lower()} true", java_main(body))


@family("java.overflow", "java", 3, "Переполнение int")
def _(rng):
    k, m = rng.randint(1, 20), rng.randint(21, 90)
    if rng.random() < 0.5:
        body = f"int x = Integer.MAX_VALUE - {k};\nx += {m};\nSystem.out.println(x);"
        ans = str(wrap32(INT_MAX - k + m))
    else:
        body = (
            f"long big = Integer.MAX_VALUE + {m};\nlong safe = Integer.MAX_VALUE + (long) {m};\n"
            'System.out.println(big + " " + safe);'
        )
        ans = f"{wrap32(INT_MAX + m)} {INT_MAX + m}"
    return java_text(ans, java_main(body))


_HIERARCHIES = [
    ("Animal", "Cat"),
    ("Shape", "Circle"),
    ("Vehicle", "Truck"),
    ("Account", "Deposit"),
    ("Event", "Click"),
]


@family("java.dispatch", "java", 4, "Перегрузка и переопределение: что выбирается и когда")
def _(rng):
    base, sub = rng.choice(_HIERARCHIES)
    declared, runtime = rng.choice([(base, base), (base, sub), (sub, sub)])
    members = (
        f'static class {base} {{\n    String name() {{ return "{base}"; }}\n}}\n\n'
        f'static class {sub} extends {base} {{\n    @Override\n    String name() {{ return "{sub}"; }}\n}}\n\n'
        f'static String kind({base} x) {{ return "{base.lower()}"; }}\n\n'
        f'static String kind({sub} x) {{ return "{sub.lower()}"; }}'
    )
    body = f'{declared} x = new {runtime}();\nSystem.out.println(x.name() + " " + kind(x));'
    return java_text(f"{runtime} {declared.lower()}", java_main(body, members))


@family("java.stream_lazy", "java", 4, "Ленивость Stream API и короткое замыкание")
def _(rng):
    xs = rng.sample(range(1, 60), rng.randint(6, 8))
    t = rng.choice(sorted(xs)[1:-1])
    k = rng.randint(2, 5)
    with_map = rng.random() < 0.5
    idx = next(i for i, x in enumerate(xs) if x > t)
    value = xs[idx] * k if with_map else xs[idx]
    body = (
        f"List<Integer> xs = List.of({', '.join(map(str, xs))});\n"
        "int[] seen = { 0 };\n"
        "Optional<Integer> first = xs.stream()\n"
        "        .peek(x -> seen[0]++)\n"
        f"        .filter(x -> x > {t})\n"
        + (f"        .map(x -> x * {k})\n" if with_map else "")
        + "        .findFirst();\n"
        'System.out.println(first.orElse(-1) + " " + seen[0]);'
    )
    return java_text(f"{value} {idx + 1}", java_main(body, imports="import java.util.*;"))


@family("java.finally", "java", 5, "try / catch / finally и return")
def _(rng):
    limit, k = rng.randint(10, 30), rng.randint(2, 5)
    a, b = rng.randint(1, limit), rng.randint(limit + 1, limit + 20)
    if rng.random() < 0.5:
        a, b = b, a
    override = rng.random() < 0.5
    fin = "    calls++;\n" + ("    if (x % 2 == 0) {\n        return 0;\n    }\n" if override else "")
    members = (
        "static int calls = 0;\n\n"
        "static int f(int x) {\n"
        "    try {\n"
        f"        if (x > {limit}) {{\n"
        '            throw new IllegalArgumentException("too big");\n'
        "        }\n"
        f"        return x * {k};\n"
        "    } catch (IllegalArgumentException e) {\n"
        "        return -1;\n"
        "    } finally {\n"
        f"{textwrap.indent(fin, '    ')}"
        "    }\n"
        "}"
    )

    def f(x):
        if override and x % 2 == 0:
            return 0
        return -1 if x > limit else x * k

    body = f'System.out.println(f({a}) + " " + f({b}) + " " + calls);'
    return java_text(f"{f(a)} {f(b)} 2", java_main(body, members))
