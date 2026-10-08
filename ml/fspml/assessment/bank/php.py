"""Семейства заданий: PHP 8.

Ответ вычисляется Python-моделью семантики PHP 8 (нестрогое сравнение, копирование массивов,
ссылки в foreach, позднее статическое связывание). Тест `test_lang_families_match_runtime`
исполняет код настоящим интерпретатором PHP и сверяет вывод.
"""

from __future__ import annotations

from ..items import family, multi, number, text
from ._util import WORDS

PREDICT = "Что выведет скрипт? Если значений несколько — введите их через пробел."


def php_item(answer, body: str, prompt: str = PREDICT, normalize: str = "ci"):
    code = "<?php\n\n" + body.strip("\n")
    if isinstance(answer, int):
        item = number(prompt, answer, code=code, code_lang="php")
    else:
        item = text(prompt, answer, normalize=normalize, code=code, code_lang="php")
    item.explanation = "php"  # маркер для сверки с настоящим PHP в тестах
    return item


@family("php.int_division", "php", 1, "intdiv, % и деление /")
def _(rng):
    b = rng.choice([2, 4, 5, 8])
    a = rng.randint(10, 99)
    div = str(a // b) if a % b == 0 else repr(a / b)
    body = f'$a = {a};\n$b = {b};\necho intdiv($a, $b), " ", $a % $b, " ", $a / $b;'
    return php_item(f"{a // b} {a % b} {div}", body)


@family("php.foreach_sum", "php", 1, "foreach и continue")
def _(rng):
    xs = rng.sample(range(1, 40), rng.randint(5, 8))
    m = rng.randint(2, 4)
    r = rng.randint(0, m - 1)
    body = (
        f"$xs = [{', '.join(map(str, xs))}];\n"
        "$total = 0;\n"
        "foreach ($xs as $x) {\n"
        f"    if ($x % {m} === {r}) {{\n        continue;\n    }}\n"
        "    $total += $x;\n}\n"
        "echo $total;"
    )
    return php_item(sum(x for x in xs if x % m != r), body)


@family("php.null_coalescing", "php", 2, "Операторы ?? и ?:")
def _(rng):
    retries = rng.choice([0, rng.randint(1, 9)])
    t, p, f = rng.randint(10, 60), rng.choice([80, 443, 8080, 5432]), rng.randint(2, 7)
    body = (
        f"$config = ['retries' => {retries}, 'timeout' => null];\n"
        f"echo $config['retries'] ?? 5, \" \", $config['timeout'] ?? {t}, \" \", "
        f"$config['port'] ?? {p}, \" \", $config['retries'] ?: {f};"
    )
    return php_item(f"{retries} {t} {p} {retries or f}", body)


@family("php.strlen", "php", 2, "strlen и mb_strlen для UTF-8")
def _(rng):
    latin = rng.choice(WORDS)[: rng.randint(2, 5)]
    cyr = rng.choice(["код", "сервер", "данные", "тест", "ключ", "заказ"])
    s = latin + cyr if rng.random() < 0.5 else cyr + latin
    body = f'$s = "{s}";\necho strlen($s), " ", mb_strlen($s);'
    return php_item(f"{len(s.encode())} {len(s)}", body)


_LOOSE = [
    ('0 == "a"', False),
    ('"1" == "01"', True),
    ('"10" == "1e1"', True),
    ('100 == "1e2"', True),
    ('"abc" == 0', False),
    ("null == false", True),
    ("[] == false", True),
    ('"0" == false', True),
    ('"" == null', True),
    ('"1" === "01"', False),
    ('0 == ""', False),
    ('"0.0" == "0"', True),
    ("null == 0", True),
    ('"null" == null', False),
    ('"abc" == "ABC"', False),
    ("1.0 === 1", False),
]


@family("php.loose_comparison", "php", 2, "Нестрогое сравнение в PHP 8")
def _(rng):
    true_ = [e for e, v in _LOOSE if v]
    false_ = [e for e, v in _LOOSE if not v]
    k = rng.randint(2, 3)
    return multi(
        rng,
        "Какие выражения в PHP 8 равны `true`?",
        rng.sample(true_, k),
        rng.sample(false_, 5 - k),
        n_options=5,
    )


@family("php.array_copy", "php", 2, "Массивы копируются, объекты — нет")
def _(rng):
    xs = rng.sample(range(1, 30), rng.randint(2, 4))
    v, p, r = rng.randint(30, 60), rng.randint(1, 9), rng.randint(10, 99)
    by_ref = rng.random() < 0.3
    clone = rng.random() < 0.3
    body = (
        f"$a = [{', '.join(map(str, xs))}];\n"
        f"$b = {'&' if by_ref else ''}$a;\n"
        f"$b[] = {v};\n"
        "$o = new stdClass();\n"
        f"$o->n = {p};\n"
        f"$q = {'clone ' if clone else ''}$o;\n"
        f"$q->n = {r};\n"
        'echo count($a), " ", $o->n;'
    )
    return php_item(f"{len(xs) + by_ref} {p if clone else r}", body)


@family("php.static_var", "php", 2, "Статические переменные функции, ++$i и $i++")
def _(rng):
    s, m = rng.randint(0, 20), rng.randint(2, 5)
    pre = rng.random() < 0.5
    name = rng.choice(["nextId", "counter", "tick"])
    body = (
        f"function {name}() {{\n"
        f"    static $id = {s};\n"
        f"    return {'++$id' if pre else '$id++'};\n"
        "}\n\n" + f"{name}();\n" * (m - 1) + f"echo {name}();"
    )
    return php_item(s + m if pre else s + m - 1, body)


@family("php.match_switch", "php", 3, "switch сравнивает нестрого, match — строго")
def _(rng):
    value = rng.choice(['"1"', "1", '"01"', "1.0", '"abc"'])
    int_first = rng.random() < 0.5
    cases = [
        '    case 1:\n        $s = "int";\n        break;',
        '    case "1":\n        $s = "string";\n        break;',
    ]
    if not int_first:
        cases.reverse()
    body = (
        f"$value = {value};\n\n"
        "switch ($value) {\n" + "\n".join(cases) + '\n    default:\n        $s = "other";\n}\n\n'
        "$m = match ($value) {\n"
        '    1 => "int",\n    "1" => "string",\n    default => "other",\n};\n\n'
        'echo $s, " ", $m;'
    )
    # switch: "abc" не равен ни 1, ни "1"; остальные значения нестрого равны обоим — срабатывает первый case
    switch = "other" if value == '"abc"' else ("int" if int_first else "string")
    match = {"1": "int", '"1"': "string"}.get(value, "other")
    return php_item(f"{switch} {match}", body)


@family("php.array_filter", "php", 3, "array_filter сохраняет ключи")
def _(rng):
    m = rng.randint(2, 3)
    while True:
        xs = rng.sample(range(1, 40), rng.randint(5, 7))
        if any(x % m == 0 for x in xs):
            break
    body = (
        f"$xs = [{', '.join(map(str, xs))}];\n"
        f"$picked = array_filter($xs, fn($x) => $x % {m} === 0);\n"
        'echo count($picked), " ", array_key_first($picked), " ", $picked[0] ?? -1;'
    )
    first_key = next(i for i, x in enumerate(xs) if x % m == 0)
    zero = xs[0] if xs[0] % m == 0 else -1
    return php_item(f"{sum(x % m == 0 for x in xs)} {first_key} {zero}", body)


@family("php.closures", "php", 3, "Замыкания: use, use по ссылке и стрелочные функции")
def _(rng):
    a, b = rng.sample(range(2, 30), 2)
    k = rng.randint(2, 9)
    form = rng.choice(["use", "ref", "arrow"])
    fn = {
        "use": f"function () use ($x) {{\n    return $x * {k};\n}}",
        "ref": f"function () use (&$x) {{\n    return $x * {k};\n}}",
        "arrow": f"fn() => $x * {k}",
    }[form]
    body = f"$x = {a};\n$f = {fn};\n$x = {b};\necho $f();"
    return php_item((b if form == "ref" else a) * k, body)


@family("php.foreach_reference", "php", 4, "foreach по ссылке и повторное использование переменной")
def _(rng):
    xs = rng.sample(range(1, 50), rng.randint(3, 5))
    k = rng.randint(1, 9)
    unset = rng.random() < 0.3
    var = rng.choice(["item", "v", "row"])
    body = (
        f"$items = [{', '.join(map(str, xs))}];\n"
        f"foreach ($items as &${var}) {{\n    ${var} += {k};\n}}\n"
        + (f"unset(${var});\n" if unset else "")
        + f"foreach ($items as ${var}) {{\n}}\n"
        'echo implode(",", $items);'
    )
    ys = [x + k for x in xs]
    if not unset:
        ys[-1] = ys[-2]
    return php_item(",".join(map(str, ys)), body, normalize="nospace")


_CLASSES = [
    ("Model", "User"),
    ("Repository", "OrderRepository"),
    ("Shape", "Circle"),
    ("Controller", "ApiController"),
]


@family("php.late_static_binding", "php", 5, "self:: и static:: (позднее статическое связывание)")
def _(rng):
    base, sub = rng.choice(_CLASSES)
    methods = {
        "create": lambda cls: cls,  # get_class(Cls::create()) — new static()
        "selfName": lambda cls: base,
        "staticName": lambda cls: cls,
    }
    calls = [(rng.choice([base, sub]), m) for m in rng.sample(sorted(methods), 2)]
    if all(c == base for c, _ in calls):
        calls[0] = (sub, calls[0][1])
    body = (
        f"class {base}\n{{\n"
        "    public static function create(): static\n    {\n        return new static();\n    }\n\n"
        "    public static function selfName(): string\n    {\n        return self::class;\n    }\n\n"
        "    public static function staticName(): string\n    {\n        return static::class;\n    }\n}\n\n"
        f"class {sub} extends {base}\n{{\n}}\n\n"
        "echo "
        + ', " ", '.join(f"get_class({c}::create())" if m == "create" else f"{c}::{m}()" for c, m in calls)
        + ";"
    )
    return php_item(" ".join(methods[m](c) for c, m in calls), body)
