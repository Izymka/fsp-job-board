"""Семейства заданий: Go.

Ответ вычисляется Python-моделью семантики Go (усечение при делении, общий массив у срезов,
порядок defer, typed nil в интерфейсе). Код задания — полная программа; тест
`test_lang_families_match_runtime` собирает её настоящим Go (модуль с `go 1.22`) и сверяет вывод.
"""

from __future__ import annotations

import textwrap

from ..items import family, number, text
from ._util import NAMES, WORDS

PREDICT = "Что выведет программа? Если строк несколько — введите их через пробел."


def go_main(body: str, decls: str = "", imports: tuple[str, ...] = ("fmt",)) -> str:
    imp = (
        f'import "{imports[0]}"'
        if len(imports) == 1
        else "import (\n" + "".join(f'\t"{i}"\n' for i in imports) + ")"
    )
    dec = f"{decls.strip(chr(10))}\n\n" if decls else ""
    return f"package main\n\n{imp}\n\n{dec}func main() {{\n{textwrap.indent(body.strip(chr(10)), chr(9))}\n}}"


def go_item(answer, code: str, prompt: str = PREDICT):
    if isinstance(answer, int):
        item = number(prompt, answer, code=code, code_lang="go")
    else:
        item = text(prompt, answer, normalize="ci", code=code, code_lang="go")
    item.explanation = "go"  # маркер для сверки с настоящим Go в тестах
    return item


def go_bool(x: bool) -> str:
    return "true" if x else "false"


def trunc_divmod(a: int, b: int) -> tuple[int, int]:
    """Деление с усечением к нулю, как в Go, Java, C# и PHP."""
    q = abs(a) // abs(b) * (1 if (a >= 0) == (b > 0) else -1)
    return q, a - b * q


@family("go.loop_sum", "go", 1, "Цикл for с шагом и continue")
def _(rng):
    a, b, s = rng.randint(0, 5), rng.randint(14, 30), rng.randint(2, 4)
    m = rng.randint(3, 5)
    r = rng.randint(0, m - 1)
    body = (
        "total := 0\n"
        f"for i := {a}; i < {b}; i += {s} {{\n"
        f"\tif i%{m} == {r} {{\n\t\tcontinue\n\t}}\n"
        "\ttotal += i\n}\n"
        "fmt.Println(total)"
    )
    return go_item(sum(i for i in range(a, b, s) if i % m != r), go_main(body))


@family("go.int_division", "go", 2, "Целочисленное деление, в том числе отрицательных чисел")
def _(rng):
    a, b = rng.randint(20, 99), rng.randint(3, 9)
    if rng.random() < 0.6:
        a = -a
    while a % b == 0:
        a += 1
    q, r = trunc_divmod(a, b)
    body = f"a, b := {a}, {b}\nfmt.Println(a/b, a%b)"
    return go_item(f"{q} {r}", go_main(body))


@family("go.map", "go", 2, "Map: отсутствующий ключ, comma ok, нулевое значение")
def _(rng):
    keys = rng.sample(NAMES, 3)
    m = {k: rng.randint(1, 9) for k in keys}
    q = rng.choice(keys) if rng.random() < 0.5 else rng.choice([n for n in NAMES if n not in keys])
    z = rng.choice([n for n in NAMES if n not in keys and n != q]) if rng.random() < 0.6 else rng.choice(keys)
    k = rng.randint(2, 9)
    x = rng.choice(keys)
    lit = ", ".join(f'"{key}": {val}' for key, val in m.items())
    body = (
        f"m := map[string]int{{{lit}}}\n"
        f'v, ok := m["{q}"]\n'
        f'm["{z}"]++\n'
        f'm["{x}"] += {k}\n'
        f'fmt.Println(v, ok, m["{z}"], len(m))'
    )
    v, ok = m.get(q, 0), q in m
    m[z] = m.get(z, 0) + 1
    m[x] += k
    return go_item(f"{v} {go_bool(ok)} {m[z]} {len(m)}", go_main(body))


@family("go.runes", "go", 2, "Строки: байты и руны")
def _(rng):
    latin = rng.choice(WORDS)[: rng.randint(2, 5)]
    cyr = rng.choice(["код", "сервер", "данные", "тест", "ключ", "поток"])
    s = latin + cyr if rng.random() < 0.5 else cyr + latin
    body = f's := "{s}"\nfmt.Println(len(s), len([]rune(s)))'
    return go_item(f"{len(s.encode())} {len(s)}", go_main(body))


@family("go.slice_share", "go", 2, "Срез среза: общий массив, len и cap")
def _(rng):
    n = rng.randint(6, 9)
    xs = rng.sample(range(1, 50), n)
    i = rng.randint(1, 3)
    j = rng.randint(i + 1, n - 1)
    v = rng.randint(60, 99)
    body = (
        f"s := []int{{{', '.join(map(str, xs))}}}\n"
        f"t := s[{i}:{j}]\n"
        f"t[0] = {v}\n"
        f"fmt.Println(s[{i}], len(t), cap(t))"
    )
    return go_item(f"{v} {j - i} {n - i}", go_main(body))


@family("go.slice_append", "go", 3, "append и общий массив двух срезов")
def _(rng):
    n = rng.randint(2, 5)
    capv = n if rng.random() < 0.5 else n + rng.randint(1, 3)
    x, y = rng.sample(range(10, 99), 2)
    body = (
        f"base := make([]int, {n}, {capv})\n"
        f"a := append(base, {x})\n"
        f"b := append(base, {y})\n"
        f"fmt.Println(a[{n}], b[{n}], len(base))"
    )
    first = y if capv > n else x
    return go_item(f"{first} {y} {n}", go_main(body))


@family("go.receivers", "go", 3, "Методы с получателем-значением и получателем-указателем")
def _(rng):
    start = rng.randint(0, 10)
    calls = [(rng.choice(["AddValue", "AddPointer"]), rng.randint(1, 9)) for _ in range(rng.randint(3, 4))]
    if all(c == "AddValue" for c, _ in calls):
        calls[0] = ("AddPointer", calls[0][1])
    decls = (
        "type Counter struct {\n\tn int\n}\n\n"
        "func (c Counter) AddValue(k int) {\n\tc.n += k\n}\n\n"
        "func (c *Counter) AddPointer(k int) {\n\tc.n += k\n}"
    )
    body = f"c := Counter{{n: {start}}}\n" + "".join(f"c.{m}({k})\n" for m, k in calls) + "fmt.Println(c.n)"
    return go_item(start + sum(k for m, k in calls if m == "AddPointer"), go_main(body, decls))


@family("go.defer", "go", 3, "defer: порядок и момент вычисления аргументов")
def _(rng):
    a, b = rng.sample(range(10, 99), 2)
    n = rng.randint(2, 4)
    body = (
        'fmt.Print("start ")\n'
        f"x := {a}\n"
        "defer fmt.Println(x)\n"
        f"x = {b}\n"
        f"for i := 0; i < {n}; i++ {{\n"
        '\tdefer fmt.Print(i, " ")\n'
        "}\n"
        'fmt.Print("end ")'
    )
    ans = "start end " + " ".join(str(i) for i in reversed(range(n))) + f" {a}"
    return go_item(ans, go_main(body))


@family("go.channels", "go", 4, "Буферизованный канал, close и range")
def _(rng):
    c = rng.randint(3, 6)
    k = rng.randint(2, c)
    m = rng.randint(2, 9)
    body = (
        f"ch := make(chan int, {c})\n"
        f"for i := 1; i <= {k}; i++ {{\n\tch <- i * {m}\n}}\n"
        "first := <-ch\n"
        "close(ch)\n"
        "sum := 0\n"
        "for v := range ch {\n\tsum += v\n}\n"
        "v, ok := <-ch\n"
        "fmt.Println(first, sum, v, ok)"
    )
    return go_item(f"{m} {sum(i * m for i in range(2, k + 1))} 0 false", go_main(body))


@family("go.closures", "go", 4, "Замыкания и переменная цикла (Go 1.22+)")
def _(rng):
    k = rng.randint(2, 9)
    if rng.random() < 0.5:
        n = rng.randint(3, 6)
        j = rng.randint(0, n - 1)
        body = (
            "var fs []func() int\n"
            f"for i := 0; i < {n}; i++ {{\n"
            f"\tfs = append(fs, func() int {{ return i * {k} }})\n"
            "}\n"
            f"fmt.Println(fs[{j}]())"
        )
        ans = j * k
    else:
        a, b = rng.sample(range(2, 30), 2)
        body = f"x := {a}\nf := func() int {{ return x * {k} }}\nx = {b}\nfmt.Println(f())"
        ans = b * k
    return go_item(ans, go_main(body), prompt="Что выведет программа (Go 1.22+)?")


@family("go.nil_interface", "go", 5, "nil-указатель внутри интерфейса error")
def _(rng):
    decls = (
        "type ValidationError struct{}\n\n"
        'func (e *ValidationError) Error() string { return "invalid" }\n\n'
        "func checkTyped(ok bool) error {\n"
        "\tvar err *ValidationError\n"
        "\tif !ok {\n\t\terr = &ValidationError{}\n\t}\n"
        "\treturn err\n}\n\n"
        "func checkPlain(ok bool) error {\n"
        "\tif !ok {\n\t\treturn &ValidationError{}\n\t}\n"
        "\treturn nil\n}\n\n"
        "func checkVar(ok bool) error {\n"
        "\tvar err error\n"
        "\tif !ok {\n\t\terr = &ValidationError{}\n\t}\n"
        "\treturn err\n}"
    )
    calls = [(fn, rng.random() < 0.6) for fn in ("checkTyped", "checkPlain", "checkVar")]
    rng.shuffle(calls)
    exprs = ", ".join(f"{fn}({go_bool(ok)}) == nil" for fn, ok in calls)
    ans = " ".join(go_bool(fn != "checkTyped" and ok) for fn, ok in calls)
    return go_item(ans, go_main(f"fmt.Println({exprs})", decls))
