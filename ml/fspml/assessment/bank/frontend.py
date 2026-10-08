"""Семейства заданий: JavaScript, TypeScript, HTML/CSS, React.

JS-сниппеты не исполняются при генерации (в бэкенде нет JS-рантайма): ответ вычисляется
Python-моделью семантики. Тест `test_js_families_match_node` прогоняет экземпляры через Node.js
и сверяет вывод — так модель семантики проверяется в CI.
"""

from __future__ import annotations

from ..items import family, multi, number, single, text
from ._util import NAMES, WORDS

PREDICT_JS = (
    "Что выведет код в консоль? Введите вывод; если строк несколько — по порядку, без пробелов между ними."
)


def js_text(prompt: str, answer: str, code: str, normalize="nospace"):
    item = text(prompt, answer, normalize=normalize, code=code, code_lang="javascript")
    item.explanation = "js"  # маркер для проверки через Node.js в тестах
    return item


# ------------------------------------------------------------------------------------- JavaScript


@family("js.equality", "javascript", 1, "Сравнение == и ===")
def _(rng):
    cases = [
        ('"5"', "5", True, False),
        ("0", '""', True, False),
        ("null", "undefined", True, False),
        ("null", "0", False, False),
        ('"1"', "true", True, False),
        ("NaN", "NaN", False, False),
        ("[]", '""', True, False),
        ('"abc"', '"abc"', True, True),
        ("1", "1.0", True, True),
    ]
    a, b, eq, seq = rng.choice(cases)
    code = f"console.log({a} == {b}, {a} === {b});"
    return js_text("Что выведет код?", f"{str(eq).lower()} {str(seq).lower()}", code, normalize="ci")


@family("js.typeof", "javascript", 1, "Оператор typeof")
def _(rng):
    cases = [
        ("null", "object"),
        ("[]", "object"),
        ("() => 1", "function"),
        ("NaN", "number"),
        ("undefined", "undefined"),
        ("10n", "bigint"),
        ("Symbol('x')", "symbol"),
        ("new Date()", "object"),
        ("class A {}", "function"),
    ]
    expr, ans = rng.choice(cases)
    return single(
        rng,
        f"Что вернёт `typeof {expr}`?",
        f'"{ans}"',
        ['"object"', '"function"', '"number"', '"undefined"', '"null"', '"array"', '"string"'],
    )


@family("js.falsy", "javascript", 2, "Ложные значения")
def _(rng):
    falsy = ["0", '""', "null", "undefined", "NaN", "-0", "0n", "false"]
    truthy = ['"0"', '"false"', "[]", "{}", "-1", '" "', "Infinity", "new Boolean(false)"]
    f = rng.sample(falsy, rng.randint(2, 3))
    t = rng.sample(truthy, 5 - len(f))
    return multi(rng, "Какие из значений приводятся к `false` в `if (value)`?", f, t, n_options=5)


@family("js.array_methods", "javascript", 2, "map / filter / reduce")
def _(rng):
    xs = rng.sample(range(1, 20), rng.randint(5, 7))
    k = rng.randint(2, 4)
    m = rng.randint(2, 3)
    start = rng.randint(0, 10)
    code = f"const xs = [{', '.join(map(str, xs))}];\nconst r = xs.map(x => x * {k}).filter(x => x % {m} === 0).reduce((acc, x) => acc + x, {start});\nconsole.log(r);"
    ans = start + sum(x * k for x in xs if (x * k) % m == 0)
    return js_text(PREDICT_JS, str(ans), code)


@family("js.var_let", "javascript", 2, "var / let в циклах и замыканиях")
def _(rng):
    n = rng.randint(2, 4)
    kw = rng.choice(["var", "let"])
    code = f"const fs = [];\nfor ({kw} i = 0; i < {n}; i++) {{\n  fs.push(() => i);\n}}\nconsole.log(fs.map(f => f()).join(''));"
    ans = "".join(str(n) for _ in range(n)) if kw == "var" else "".join(str(i) for i in range(n))
    return js_text(PREDICT_JS, ans, code)


@family("js.event_loop", "javascript", 3, "Event loop: макро- и микрозадачи")
def _(rng):
    letters = rng.sample("ABCDEFGHKMNPRSTX", 4)
    parts = [("sync", letters[0]), ("timeout", letters[1]), ("promise", letters[2]), ("sync", letters[3])]
    rng.shuffle(parts)
    lines = []
    for kind, ch in parts:
        if kind == "sync":
            lines.append(f"console.log('{ch}');")
        elif kind == "timeout":
            lines.append(f"setTimeout(() => console.log('{ch}'), 0);")
        else:
            lines.append(f"Promise.resolve().then(() => console.log('{ch}'));")
    order_ = (
        [ch for k, ch in parts if k == "sync"]
        + [ch for k, ch in parts if k == "promise"]
        + [ch for k, ch in parts if k == "timeout"]
    )
    return js_text(PREDICT_JS, "".join(order_), "\n".join(lines))


@family("js.closure_counter", "javascript", 3, "Замыкания: счётчики")
def _(rng):
    step = rng.randint(1, 5)
    calls_a, calls_b = rng.randint(1, 3), rng.randint(1, 3)
    code = (
        "function makeCounter(step) {\n  let n = 0;\n  return () => (n += step);\n}\n"
        f"const a = makeCounter({step});\nconst b = makeCounter({step + 1});\n"
        + "a();\n" * (calls_a - 1)
        + "b();\n" * (calls_b - 1)
        + "console.log(a() + b());"
    )
    ans = step * calls_a + (step + 1) * calls_b
    return js_text(PREDICT_JS, str(ans), code)


@family("js.this", "javascript", 3, "this в методах и стрелочных функциях")
def _(rng):
    name = rng.choice(NAMES)
    variant = rng.choice(["method", "extracted", "arrow_in_method", "bind"])
    head = f"'use strict';\nconst obj = {{\n  name: '{name}',\n"
    if variant == "method":
        code = head + "  get() { return this ? this.name : 'undefined'; }\n};\nconsole.log(obj.get());"
        ans = name
    elif variant == "extracted":
        code = (
            head
            + "  get() { return this ? this.name : 'undefined'; }\n};\nconst g = obj.get;\nconsole.log(g());"
        )
        ans = "undefined"
    elif variant == "arrow_in_method":
        code = head + "  get() { const f = () => this.name; return f(); }\n};\nconsole.log(obj.get());"
        ans = name
    else:
        other = rng.choice([n for n in NAMES if n != name])
        code = (
            head
            + f"  get() {{ return this.name; }}\n}};\nconst g = obj.get.bind({{ name: '{other}' }});\nconsole.log(g.call(obj));"
        )
        ans = other
    return js_text(PREDICT_JS, ans, code, normalize="ci")


@family("js.hoisting", "javascript", 4, "Всплытие и временная мёртвая зона")
def _(rng):
    v = rng.randint(1, 9)
    variant = rng.choice(["var", "let", "func", "func_expr"])
    if variant == "var":
        code = f"console.log(typeof x, x);\nvar x = {v};"
        ans = "undefined undefined"
    elif variant == "let":
        code = f"try {{\n  console.log(x);\n}} catch (e) {{\n  console.log(e.name);\n}}\nlet x = {v};"
        ans = "ReferenceError"
    elif variant == "func":
        code = f"console.log(f());\nfunction f() {{ return {v}; }}"
        ans = str(v)
    else:
        code = f"try {{\n  console.log(f());\n}} catch (e) {{\n  console.log(e.name);\n}}\nvar f = function () {{ return {v}; }};"
        ans = "TypeError"
    return js_text(PREDICT_JS, ans, code, normalize="ci")


@family("js.async_order", "javascript", 4, "async/await и порядок выполнения")
def _(rng):
    a, b, c, d, e = rng.sample("ABCDEFGHKMNPRSTX", 5)
    code = (
        "async function f() {\n"
        f"  console.log('{a}');\n"
        "  await null;\n"
        f"  console.log('{b}');\n"
        "}\n"
        f"console.log('{c}');\n"
        f"setTimeout(() => console.log('{d}'), 0);\n"
        "f();\n"
        f"console.log('{e}');"
    )
    return js_text(PREDICT_JS, c + a + e + b + d, code)


@family("js.spread_copy", "javascript", 4, "Поверхностное копирование объектов")
def _(rng):
    v1, v2, v3 = rng.sample(range(1, 50), 3)
    method = rng.choice(["{ ...a }", "Object.assign({}, a)", "structuredClone(a)"])
    code = (
        f"const a = {{ x: {v1}, inner: {{ y: {v2} }} }};\n"
        f"const b = {method};\n"
        f"b.x = {v3};\n"
        f"b.inner.y = {v3};\n"
        "console.log(a.x + a.inner.y);"
    )
    deep = method.startswith("structuredClone")
    ans = v1 + (v2 if deep else v3)
    return js_text(PREDICT_JS, str(ans), code)


@family("js.microtasks_nested", "javascript", 5, "Вложенные микрозадачи и таймеры")
def _(rng):
    L = rng.sample("ABCDEFGHKMNPRSTX", 6)
    code = (
        f"setTimeout(() => console.log('{L[0]}'), 0);\n"
        "Promise.resolve().then(() => {\n"
        f"  console.log('{L[1]}');\n"
        f"  setTimeout(() => console.log('{L[2]}'), 0);\n"
        f"  Promise.resolve().then(() => console.log('{L[3]}'));\n"
        "});\n"
        f"queueMicrotask(() => console.log('{L[4]}'));\n"
        f"console.log('{L[5]}');"
    )
    ans = L[5] + L[1] + L[4] + L[3] + L[0] + L[2]
    return js_text(PREDICT_JS, ans, code)


@family("js.prototype", "javascript", 5, "Прототипы и свойства")
def _(rng):
    k1, k2 = rng.sample(WORDS, 2)
    v = rng.randint(1, 9)
    code = (
        f"const base = {{ {k1}: {v} }};\n"
        "const obj = Object.create(base);\n"
        f"obj.{k2} = {v + 1};\n"
        f"console.log('{k1}' in obj, obj.hasOwnProperty('{k1}'), Object.keys(obj).length, obj.{k1});"
    )
    ans = f"true false 1 {v}"
    return js_text("Что выведет код?", ans, code, normalize="ci")


@family("js.number_quirks", "javascript", 3, "Числа и преобразования типов")
def _(rng):
    cases = [
        ("console.log(0.1 + 0.2 === 0.3);", "false"),
        ("console.log([1, 10, 2].sort().join(','));", "1,10,2"),
        ("console.log('5' - 2, '5' + 2);", "3 52"),
        ("console.log(parseInt('08px'), Number('08px'));", "8 NaN"),
        ("console.log(typeof ([] + []), [] + {} === '[object Object]');", "string true"),
        ("console.log(Math.max() < Math.min());", "true"),
        ("console.log(+true + +'3');", "4"),
    ]
    code, ans = rng.choice(cases)
    return js_text("Что выведет код?", ans, code, normalize="ci")


# ------------------------------------------------------------------------------------- TypeScript


@family("ts.utility", "typescript", 3, "Утилитарные типы")
def _(rng):
    fields = rng.sample(["id: number", "name: string", "email: string", "age: number", "active: boolean"], 3)
    names = [f.split(":")[0] for f in fields]
    util = rng.choice(["Pick", "Omit", "Partial", "Required"])
    iface = "interface User { " + "; ".join(fields) + " }"
    if util == "Pick":
        expr, ans = f"Pick<User, '{names[0]}'>", "{ " + fields[0] + " }"
    elif util == "Omit":
        expr, ans = f"Omit<User, '{names[0]}'>", "{ " + "; ".join(fields[1:]) + " }"
    elif util == "Partial":
        expr, ans = "Partial<User>", "{ " + "; ".join(f.replace(":", "?:") for f in fields) + " }"
    else:
        expr, ans = "Required<Partial<User>>", "{ " + "; ".join(fields) + " }"
    distractors = [
        "{ " + fields[0] + " }",
        "{ " + "; ".join(fields[1:]) + " }",
        "{ " + "; ".join(f.replace(":", "?:") for f in fields) + " }",
        "{ " + "; ".join(fields) + " }",
        "{ " + fields[0].replace(":", "?:") + " }",
    ]
    return single(
        rng, f"Какой тип эквивалентен `{expr}`?", ans, distractors, code=iface, code_lang="typescript"
    )


@family("ts.narrowing", "typescript", 2, "Сужение типов")
def _(rng):
    variant = rng.choice(["typeof", "in", "truthy", "eq"])
    if variant == "typeof":
        code = "function f(x: string | number | boolean) {\n  if (typeof x === 'number' || typeof x === 'boolean') return;\n  x; // ?\n}"
        ans = "string"
    elif variant == "in":
        code = "type Cat = { meow(): void };\ntype Dog = { bark(): void };\nfunction f(p: Cat | Dog) {\n  if ('bark' in p) {\n    p; // ?\n  }\n}"
        ans = "Dog"
    elif variant == "truthy":
        code = "function f(x: string | null | undefined) {\n  if (x) {\n    x; // ?\n  }\n}"
        ans = "string"
    else:
        code = "function f(x: 'a' | 'b' | 'c', y: 'b' | 'd') {\n  if (x === y) {\n    x; // ?\n  }\n}"
        ans = "'b'"
    return single(
        rng,
        "Какой тип у `x` (или `p`) в отмеченной строке?",
        ans,
        ["string", "Dog", "Cat", "'b'", "never", "string | null", "unknown"],
        code=code,
        code_lang="typescript",
    )


@family("ts.structural", "typescript", 3, "Структурная типизация")
def _(rng):
    variant = rng.choice(["extra_var", "extra_literal", "missing", "readonly"])
    if variant == "extra_var":
        code = "type P = { x: number };\nconst src = { x: 1, y: 2 };\nconst p: P = src;"
        ans = "Компилируется"
    elif variant == "extra_literal":
        code = "type P = { x: number };\nconst p: P = { x: 1, y: 2 };"
        ans = "Ошибка: лишнее свойство в объектном литерале"
    elif variant == "missing":
        code = "type P = { x: number; y: number };\nconst p: P = { x: 1 };"
        ans = "Ошибка: не хватает свойства"
    else:
        code = "const xs: readonly number[] = [1, 2];\nxs.push(3);"
        ans = "Ошибка: у readonly-массива нет push"
    pool = [
        "Компилируется",
        "Ошибка: лишнее свойство в объектном литерале",
        "Ошибка: не хватает свойства",
        "Ошибка: у readonly-массива нет push",
        "Ошибка во время выполнения",
    ]
    return single(rng, "Скомпилируется ли код (strict)?", ans, pool, code=code, code_lang="typescript")


@family("ts.keyof", "typescript", 4, "keyof, typeof и индексные типы")
def _(rng):
    keys = rng.sample(["host", "port", "debug", "user", "timeout"], 3)
    vals = {"host": "'localhost'", "port": "8080", "debug": "true", "user": "'admin'", "timeout": "30"}
    obj = "const config = { " + ", ".join(f"{k}: {vals[k]}" for k in keys) + " } as const;"
    variant = rng.choice(["keyof", "value"])
    if variant == "keyof":
        expr = "keyof typeof config"
        ans = " | ".join(f'"{k}"' for k in keys)
        distractors = ["string", "string[]", " | ".join(vals[k] for k in keys), '"' + keys[0] + '"']
    else:
        expr = f"(typeof config)['{keys[1]}']"
        ans = vals[keys[1]].replace("'", '"')
        distractors = [
            "string",
            "number",
            "boolean",
            "any",
            " | ".join(vals[k].replace("'", '"') for k in keys),
        ]
    return single(rng, f"Какой тип у `{expr}`?", ans, distractors, code=obj, code_lang="typescript")


@family("ts.conditional", "typescript", 5, "Условные и распределённые типы")
def _(rng):
    variant = rng.choice(["dist", "nodist", "infer", "exclude"])
    if variant == "dist":
        code = "type F<T> = T extends string ? 'S' : 'N';\ntype R = F<string | number>;"
        ans = "'S' | 'N'"
    elif variant == "nodist":
        code = "type F<T> = [T] extends [string] ? 'S' : 'N';\ntype R = F<string | number>;"
        ans = "'N'"
    elif variant == "infer":
        code = "type Elem<T> = T extends (infer U)[] ? U : never;\ntype R = Elem<string[] | number>;"
        ans = "string"
    else:
        code = "type R = Exclude<'a' | 'b' | 'c', 'a' | 'x'>;"
        ans = "'b' | 'c'"
    return single(
        rng,
        "Чему равен тип `R`?",
        ans,
        ["'S' | 'N'", "'N'", "'S'", "string", "never", "'b' | 'c'", "'a'"],
        code=code,
        code_lang="typescript",
    )


# --------------------------------------------------------------------------------------- HTML/CSS


@family("css.box_model", "html_css", 1, "Блочная модель")
def _(rng):
    w = rng.randrange(100, 400, 10)
    p = rng.randint(5, 30)
    b = rng.randint(1, 5)
    m = rng.randint(0, 20)
    sizing = rng.choice(["content-box", "border-box"])
    total = w if sizing == "border-box" else w + 2 * p + 2 * b
    code = f".card {{\n  box-sizing: {sizing};\n  width: {w}px;\n  padding: {p}px;\n  border: {b}px solid #402FFF;\n  margin: {m}px;\n}}"
    return number(
        "Какова видимая ширина элемента (от внешнего края рамки до внешнего края рамки) в пикселях?",
        total,
        code=code,
        code_lang="css",
    )


@family("css.specificity", "html_css", 2, "Специфичность селекторов")
def _(rng):
    colors = rng.sample(["red", "blue", "green", "orange", "purple"], 4)
    sels = [
        ("#main .item", (1, 1, 0)),
        (".list .item", (0, 2, 0)),
        ("ul li.item", (0, 1, 2)),
        ("li", (0, 0, 1)),
        (".item:hover", (0, 2, 0)),
        ("#main li", (1, 0, 1)),
        ("ul > li", (0, 0, 2)),
    ]
    chosen = rng.sample(sels, 3)
    best = max(chosen, key=lambda s: s[1])
    while sum(1 for s in chosen if s[1] == best[1]) > 1 or any(s[0].endswith(":hover") for s in chosen):
        chosen = rng.sample(sels, 3)
        best = max(chosen, key=lambda s: s[1])
    rules = "\n".join(f"{s[0]} {{ color: {c}; }}" for s, c in zip(chosen, colors))
    html = '<ul id="main" class="list"><li class="item">Текст</li></ul>'
    ans = colors[chosen.index(best)]
    return single(
        rng, f"Каким цветом будет текст? Разметка: `{html}`", ans, colors[:3], code=rules, code_lang="css"
    )


@family("css.flex_grow", "html_css", 3, "Flexbox: распределение свободного места")
def _(rng):
    W = rng.randrange(600, 1000, 20)
    bases = [rng.randrange(50, 150, 10) for _ in range(3)]
    grows = [rng.randint(0, 3) for _ in range(3)]
    if sum(grows) == 0:
        grows[0] = 1
    free = W - sum(bases)
    i = rng.randint(0, 2)
    width = bases[i] + free * grows[i] / sum(grows)
    code = f".row {{ display: flex; width: {W}px; }}\n" + "\n".join(
        f".item{j + 1} {{ flex: {g} 0 {b}px; }}" for j, (g, b) in enumerate(zip(grows, bases))
    )
    return number(
        f"Какой будет ширина `.item{i + 1}` в пикселях (без отступов и рамок; округлите до целого)?",
        round(width),
        tolerance=1,
        code=code,
        code_lang="css",
    )


@family("css.margin_collapse", "html_css", 4, "Схлопывание вертикальных отступов")
def _(rng):
    m1 = rng.randrange(10, 60, 5)
    m2 = rng.randrange(10, 60, 5)
    neg = rng.random() < 0.3
    if neg:
        m2 = -m2
    flex = rng.random() < 0.3
    if flex:
        ans = m1 + m2
    elif neg:
        ans = m1 + m2 if m1 > 0 > m2 else max(m1, m2)
    else:
        ans = max(m1, m2)
    parent = ".wrap { display: flex; flex-direction: column; }" if flex else ".wrap { display: block; }"
    code = f"{parent}\n.a {{ margin-bottom: {m1}px; }}\n.b {{ margin-top: {m2}px; }}"
    return number(
        "Блоки `.a` и `.b` идут подряд внутри `.wrap`. Каково расстояние между ними по вертикали (px)?",
        ans,
        code=code,
        code_lang="css",
    )


@family("html.semantics", "html_css", 1, "Семантическая разметка и доступность")
def _(rng):
    cases = [
        ("основная навигация сайта", "<nav>"),
        ("самостоятельная публикация (статья блога)", "<article>"),
        ("кнопка, отправляющая форму", '<button type="submit">'),
        ("подпись к полю ввода email", '<label for="email">'),
        ("основное содержимое страницы (одно на странице)", "<main>"),
        ("подвал страницы с контактами", "<footer>"),
        ("заголовок верхнего уровня страницы", "<h1>"),
    ]
    need, ans = rng.choice(cases)
    return single(
        rng,
        f"Какой элемент семантически корректен для: {need}?",
        ans,
        [c[1] for c in cases if c[1] != ans] + ["<div>", "<span>"],
    )


@family("css.position", "html_css", 3, "Позиционирование и контекст наложения")
def _(rng):
    cases = [
        (
            "Элемент с `position: absolute` позиционируется относительно…",
            "ближайшего предка с position, отличным от static",
            ["родителя в любом случае", "окна браузера всегда", "body"],
        ),
        (
            "Элемент с `position: sticky` перестаёт «прилипать», когда…",
            "его контейнер прокручен за пределы видимой области",
            ["пользователь кликает по нему", "задан z-index", "у родителя display:flex"],
        ),
        (
            "`z-index: 999` у ребёнка не поднимает его над соседом родителя, потому что…",
            "родитель создаёт свой контекст наложения",
            [
                "z-index работает только у position: fixed",
                "максимальный z-index — 100",
                "z-index наследуется",
            ],
        ),
        (
            "Какое свойство убирает элемент из потока, но оставляет место под него?",
            "visibility: hidden",
            ["display: none", "opacity: 0 и position: absolute", "height: 0"],
        ),
    ]
    q, a, d = rng.choice(cases)
    return single(rng, q, a, d)


# ------------------------------------------------------------------------------------------ React


@family("react.batching", "react", 2, "Обновление состояния и батчинг")
def _(rng):
    start = rng.randint(0, 5)
    n = rng.randint(2, 4)
    functional = rng.random() < 0.5
    inc = rng.randint(1, 3)
    call = f"setCount(c => c + {inc});" if functional else f"setCount(count + {inc});"
    code = (
        f"const [count, setCount] = useState({start});\n"
        "function onClick() {\n" + "".join(f"  {call}\n" for _ in range(n)) + "}"
    )
    ans = start + (n * inc if functional else inc)
    return number("Каким будет `count` после одного клика (React 18)?", ans, code=code, code_lang="jsx")


@family("react.effects", "react", 3, "useEffect и массив зависимостей")
def _(rng):
    renders = rng.randint(3, 6)
    changes = sorted(rng.sample(range(2, renders + 1), rng.randint(1, max(1, renders - 2))))
    deps = rng.choice(["[]", "[id]", "нет массива"])
    if deps == "[]":
        ans = 1
    elif deps == "[id]":
        ans = 1 + len(changes)
    else:
        ans = renders
    dep_code = "" if deps == "нет массива" else f", {deps}"
    code = f"useEffect(() => {{\n  load(id);\n}}{dep_code});"
    prompt = (
        f"Компонент отрендерился {renders} раз(а) (без StrictMode). Проп `id` менялся перед рендерами № "
        f"{', '.join(map(str, changes))}, в остальных рендерах оставался прежним. Сколько раз вызовется `load`?"
    )
    return number(prompt, ans, code=code, code_lang="jsx")


@family("react.keys", "react", 3, "Ключи в списках")
def _(rng):
    cases = [
        (
            "Список с полями ввода рендерится с `key={index}`; в начало списка добавили элемент",
            "Введённые значения «съедут» на соседние элементы",
        ),
        (
            "Список рендерится с `key={Math.random()}`",
            "Все элементы будут пересоздаваться при каждом рендере",
        ),
        (
            "Список рендерится с `key={item.id}` (id уникальны и стабильны)",
            "React корректно сопоставит элементы между рендерами",
        ),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng,
        f"{sit}. Что произойдёт?",
        ans,
        [c[1] for c in cases if c[1] != ans] + ["React выбросит ошибку при сборке"],
    )


@family("react.stale_closure", "react", 4, "Устаревшие замыкания в эффектах")
def _(rng):
    ticks = rng.randint(3, 6)
    functional = rng.random() < 0.5
    upd = "setN(n => n + 1)" if functional else "setN(n + 1)"
    code = (
        "const [n, setN] = useState(0);\n"
        "useEffect(() => {\n"
        f"  const id = setInterval(() => {upd}, 1000);\n"
        "  return () => clearInterval(id);\n"
        "}, []);"
    )
    ans = ticks if functional else 1
    return number(
        f"Каким будет `n` через {ticks}.5 секунды после монтирования?", ans, code=code, code_lang="jsx"
    )


@family("react.memo", "react", 4, "React.memo и стабильность пропсов")
def _(rng):
    clicks = rng.randint(2, 5)
    variant = rng.choice(["inline_obj", "memo_obj", "callback", "inline_fn"])
    if variant == "inline_obj":
        prop, ans = "style={{ color: 'red' }}", clicks
    elif variant == "memo_obj":
        prop, ans = "style={style} /* const style = useMemo(() => ({ color: 'red' }), []) */", 0
    elif variant == "callback":
        prop, ans = "onSelect={onSelect} /* const onSelect = useCallback(() => {}, []) */", 0
    else:
        prop, ans = "onSelect={() => {}}", clicks
    code = (
        "const Child = React.memo(function Child(props) {\n  return <div>child</div>;\n});\n\n"
        "function Parent() {\n  const [n, setN] = useState(0);\n"
        f"  return <><button onClick={{() => setN(n + 1)}}>{{n}}</button><Child {prop} /></>;\n}}"
    )
    return number(
        f"Сколько раз `Child` перерендерится после {clicks} кликов по кнопке (не считая первый рендер)?",
        ans,
        code=code,
        code_lang="jsx",
    )


@family("react.state_model", "react", 2, "Состояние, пропсы и поток данных")
def _(rng):
    cases = [
        (
            "Двум соседним компонентам нужно одно и то же изменяемое значение",
            "Поднять состояние в общего родителя",
        ),
        (
            "Компонент должен изменить переданный ему проп",
            "Вызвать колбэк родителя, который изменит своё состояние",
        ),
        ("Значение вычисляется из других состояний и пропсов", "Вычислять при рендере, не хранить в state"),
        ("Нужно хранить id таймера между рендерами без перерисовки", "useRef"),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng,
        f"{sit}. Как правильно поступить?",
        ans,
        [c[1] for c in cases if c[1] != ans] + ["Изменить props напрямую"],
    )


@family("css.units", "html_css", 2, "Единицы em и rem")
def _(rng):
    root = rng.choice([16, 18, 20])
    parent = rng.choice([12, 14, 20, 24])
    k = rng.choice([0.75, 1.25, 1.5, 2])
    unit = rng.choice(["em", "rem"])
    px = parent * k if unit == "em" else root * k
    q = (
        f"`html {{ font-size: {root}px }}`, у родителя `font-size: {parent}px`, у дочернего элемента "
        f"`font-size: {k}{unit}`. Каков размер шрифта дочернего элемента в px?"
    )
    return number(q, px)


@family("css.grid_fr", "html_css", 3, "CSS Grid: дробные единицы fr")
def _(rng):
    w = rng.choice([900, 1000, 1200, 1280])
    fixed = rng.choice([200, 240, 300])
    a, b = rng.choice([(1, 2), (1, 3), (2, 3), (1, 1)])
    gap = rng.choice([0, 10, 20, 24])
    free = w - fixed - 2 * gap
    which = rng.choice(["второй", "третьей"])
    width = free * (a if which == "второй" else b) / (a + b)
    q = (
        f"Контейнер шириной {w}px: `display: grid; grid-template-columns: {fixed}px {a}fr {b}fr; gap: {gap}px`. "
        f"Какова ширина {which} колонки в px? Точность 0,5."
    )
    return number(q, round(width, 2), tolerance=0.5)


@family("html.forms", "html_css", 2, "Доступные формы")
def _(rng):
    cases = [
        (
            "Как связать подпись с полем ввода, чтобы экранный диктор её озвучивал?",
            '`<label for="email">` и `id="email"` у поля',
        ),
        (
            "Как сообщить экранному диктору текст ошибки под полем?",
            "Связать текст ошибки с полем через `aria-describedby`",
        ),
        (
            "Какой тип поля даст мобильную клавиатуру для email и встроенную проверку формата?",
            '`<input type="email">`',
        ),
        (
            "Почему нельзя использовать placeholder вместо подписи поля?",
            "Он исчезает при вводе и плохо читается — подпись должна быть видимой",
        ),
    ]
    q, a = rng.choice(cases)
    return single(rng, q, a, [c[1] for c in cases if c[1] != a] + ['Добавить `tabindex="-1"` полю'])


@family("react.hooks_rules", "react", 2, "Правила хуков")
def _(rng):
    bad = [
        "if (isOpen) { const [x, setX] = useState(0) }",
        "for (const id of ids) { useEffect(() => load(id), [id]) }",
        "function handleClick() { const ref = useRef(null) }",
        "if (!user) return null; const [tab, setTab] = useState('a')",
    ]
    good = [
        "const [x, setX] = useState(0); if (isOpen) { setX(1) }",
        "useEffect(() => { if (isOpen) load() }, [isOpen])",
        "const ref = useRef(null); function handleClick() { ref.current?.focus() }",
        "function useUser(id) { return useQuery(['user', id], () => fetchUser(id)) }",
    ]
    if rng.random() < 0.5:
        return single(
            rng, "Какой фрагмент компонента **нарушает** правила хуков?", rng.choice(bad), rng.sample(good, 3)
        )
    return single(rng, "Какой фрагмент **соблюдает** правила хуков?", rng.choice(good), rng.sample(bad, 3))


@family("react.controlled", "react", 2, "Управляемые и неуправляемые поля")
def _(rng):
    cases = [
        (
            "`<input value={name} />` без onChange — поле не редактируется. Почему?",
            "Поле управляемое: значение задаёт состояние, а без onChange оно не меняется",
        ),
        (
            "Нужно валидировать ввод на каждый символ и показывать ошибку сразу",
            "Управляемое поле: value из состояния и onChange",
        ),
        (
            "Форма из 40 полей тормозит, хотя значения нужны только при отправке",
            "Неуправляемые поля (defaultValue, ref или FormData при отправке)",
        ),
        (
            "Warning: «A component is changing an uncontrolled input to be controlled». Причина?",
            "Начальное значение было undefined, затем стало строкой — нужно инициализировать ''",
        ),
    ]
    sit, a = rng.choice(cases)
    return single(rng, sit, a, [c[1] for c in cases if c[1] != a])


@family("react.context", "react", 3, "Context и лишние перерисовки")
def _(rng):
    cases = [
        (
            "Провайдер передаёт `value={{ user, setUser }}`, и все потребители перерисовываются при каждом рендере родителя. Почему?",
            "Каждый рендер создаёт новый объект value — нужно мемоизировать его (useMemo)",
        ),
        (
            "В одном контексте и тема, и часто меняющийся счётчик; компоненты, читающие только тему, перерисовываются",
            "Разделить на два контекста по частоте изменений",
        ),
        (
            "Компонент использует useContext, но получает значение по умолчанию, а не из провайдера",
            "Компонент находится вне дерева соответствующего Provider",
        ),
    ]
    sit, a = rng.choice(cases)
    return single(
        rng, sit, a, [c[1] for c in cases if c[1] != a] + ["Context нельзя менять после первого рендера"]
    )
