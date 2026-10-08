"""Семейства заданий: Vue 3 (Composition API, `<script setup>`).

Ответы вычисляются моделью поведения Vue 3: диапазон в v-for начинается с 1, computed кэшируется
до изменения зависимостей, наблюдатели с flush: 'pre' выполняются один раз за тик, DOM обновляется
после nextTick, v-if на одном элементе с v-for вычисляется раньше v-for.
"""

from __future__ import annotations

from ..items import family, number, order, single, text
from ._util import NAMES

_DIRECTIVES = [
    ("Элемент должен оставаться в DOM и только скрываться через `display: none`", "v-show"),
    ("Блок не должен создаваться в DOM, пока условие ложно", "v-if"),
    ("Отрисовать по элементу на каждую запись массива", "v-for"),
    ("Связать значение поля ввода с переменной в обе стороны", "v-model"),
    ("Подписаться на событие click", "v-on (@click)"),
    ("Привязать атрибут href к выражению", "v-bind (:href)"),
    ("Вставить HTML-разметку из строки без экранирования", "v-html"),
]


@family("vue.directives", "vue", 1, "Директивы шаблона")
def _(rng):
    situation, ans = rng.choice(_DIRECTIVES)
    return single(rng, f"{situation}. Какую директиву использовать?", ans, [d for _, d in _DIRECTIVES])


@family("vue.v_for_range", "vue", 1, "v-for по числовому диапазону")
def _(rng):
    n, k = rng.randint(3, 9), rng.randint(2, 9)
    tag = rng.choice(["span", "li", "td"])
    code = f'<template>\n  <{tag} v-for="n in {n}" :key="n">{{{{ n * {k} }}}}</{tag}>\n</template>'
    return text(
        f"Какие числа будут в первом и последнем `<{tag}>`? Введите через пробел.",
        f"{k} {n * k}",
        normalize="ci",
        code=code,
        code_lang="vue",
    )


@family("vue.computed_list", "vue", 2, "computed-список после изменения исходных данных")
def _(rng):
    xs = rng.sample(range(1, 60), rng.randint(5, 7))
    t = rng.choice(sorted(xs)[1:-1])
    v = rng.choice([x for x in range(1, 99) if x not in xs])
    code = (
        "<script setup>\n"
        "import { ref, computed } from 'vue'\n\n"
        f"const items = ref([{', '.join(map(str, xs))}])\n"
        f"const visible = computed(() => items.value.filter(x => x > {t}))\n\n"
        f"function add() {{\n  items.value.push({v})\n}}\n"
        "</script>\n\n"
        "<template>\n"
        '  <ul>\n    <li v-for="x in visible" :key="x">{{ x }}</li>\n  </ul>\n'
        '  <button @click="add">Добавить</button>\n'
        "</template>"
    )
    return number(
        "Сколько элементов `<li>` будет на странице после одного нажатия кнопки?",
        sum(x > t for x in xs + [v]),
        code=code,
        code_lang="vue",
    )


_DATAFLOW = [
    (
        "Дочерний компонент получил prop `title` и должен сообщить родителю новое значение",
        "Сгенерировать событие через emit, родитель обновит своё состояние",
    ),
    (
        "Нужна двусторонняя привязка значения к собственному компоненту `<{c} />`",
        "v-model на компоненте: prop modelValue и событие update:modelValue (или defineModel)",
    ),
    (
        "Передать настройки глубоко вложенным потомкам `<{c} />`, не пробрасывая props через все уровни",
        "provide в предке и inject в потомке",
    ),
    (
        "В дочернем компоненте `<{c} />` написали `props.title = 'Новый'`",
        "Vue выдаст предупреждение: props только для чтения, у родителя значение не изменится",
    ),
]


@family("vue.props_emit", "vue", 2, "Поток данных между компонентами")
def _(rng):
    situation, ans = rng.choice(_DATAFLOW)
    comp = rng.choice(["UserCard", "PriceInput", "OrderForm", "TagPicker"])
    return single(
        rng,
        situation.format(c=comp) + ". Как это работает или как правильно поступить?",
        ans,
        [a for _, a in _DATAFLOW] + ["Изменить prop напрямую — изменение автоматически уйдёт родителю"],
    )


@family("vue.reactive_destructure", "vue", 3, "Деструктуризация reactive и toRefs")
def _(rng):
    a, s, k = rng.randint(0, 20), rng.randint(1, 9), rng.randint(1, 9)
    field = rng.choice(["count", "total", "score"])
    if rng.random() < 0.5:
        code = (
            "<script setup>\n"
            "import { reactive } from 'vue'\n\n"
            f"const state = reactive({{ {field}: {a}, step: {s} }})\n"
            f"let {{ {field} }} = state\n"
            f"{field} += {k}\n"
            f"state.{field} += state.step\n"
            f"console.log(state.{field}, {field})\n"
            "</script>"
        )
        ans = f"{a + s} {a + k}"
    else:
        code = (
            "<script setup>\n"
            "import { reactive, toRefs } from 'vue'\n\n"
            f"const state = reactive({{ {field}: {a}, step: {s} }})\n"
            f"const {{ {field} }} = toRefs(state)\n"
            f"{field}.value += {k}\n"
            f"state.{field} += state.step\n"
            f"console.log(state.{field}, {field}.value)\n"
            "</script>"
        )
        ans = f"{a + k + s} {a + k + s}"
    return text(
        "Что выведет `console.log`? Введите два числа через пробел.",
        ans,
        code=code,
        code_lang="vue",
        normalize="ci",
    )


@family("vue.computed_cache", "vue", 3, "Кэширование computed и вызов методов в шаблоне")
def _(rng):
    m = rng.randint(1, 3)
    r, c = rng.randint(1, 5), rng.randint(0, 3)
    p = rng.randint(100, 900)
    code = (
        "<script setup>\n"
        "import { ref, computed } from 'vue'\n\n"
        f"const price = ref({p})\n"
        "const clicks = ref(0)\n"
        "const total = computed(() => price.value * 2)\n"
        "function totalFn() {\n  return price.value * 2\n}\n"
        "</script>\n\n"
        "<template>\n"
        f"  <p>{' '.join(['{{ total }}'] * m)}</p>\n"
        f"  <p>{' '.join(['{{ totalFn() }}'] * m)}</p>\n"
        '  <button @click="clicks++">{{ clicks }}</button>\n'
        "</template>"
    )
    prompt = (
        f"После первого рендера кнопку нажали {r} раз(а), и ещё {c} раз(а) отдельно меняли `price` на новое "
        "значение — каждое изменение даёт отдельный перерендер. Сколько раз всего вычислится геттер `total` "
        "и сколько раз вызовется `totalFn`, считая первый рендер? Введите два числа через пробел."
    )
    return text(prompt, f"{1 + c} {m * (1 + r + c)}", code=code, code_lang="vue", normalize="ci")


_PARENTS = [("App", "Sidebar"), ("OrderPage", "OrderItem"), ("Dashboard", "Chart"), ("Profile", "Avatar")]


@family("vue.lifecycle_order", "vue", 3, "Порядок хуков родителя и дочернего компонента")
def _(rng):
    parent, child = rng.choice(_PARENTS)
    steps = [
        f"{parent}: setup",
        f"{parent}: onBeforeMount",
        f"{child}: setup",
        f"{child}: onBeforeMount",
        f"{child}: onMounted",
        f"{parent}: onMounted",
    ]
    del steps[rng.choice([0, 2, 3])]
    return order(
        rng,
        f"Компонент `{parent}` содержит в шаблоне `<{child} />`. Расположите события монтирования по порядку.",
        steps,
    )


@family("vue.v_if_v_for", "vue", 4, "v-if и v-for на одном элементе")
def _(rng):
    coll, var = rng.choice([("users", "user"), ("orders", "order"), ("tasks", "task"), ("items", "item")])
    flag = rng.choice(["active", "visible", "done", "paid"])
    code = f'<li v-for="{var} in {coll}" v-if="{var}.{flag}" :key="{var}.id">\n  {{{{ {var}.name }}}}\n</li>'
    correct = f"v-if выполнится раньше v-for: переменная {var} ещё не определена, при рендере будет ошибка"
    wrong = [
        f"Отрисуются только элементы с {var}.{flag} = true",
        "v-for выполнится раньше, v-if отфильтрует элементы — это рекомендуемый способ",
        "Шаблон не скомпилируется: две директивы на одном элементе запрещены",
        f"Отрисуются все элементы {coll}, v-if будет проигнорирован",
    ]
    return single(rng, "Что произойдёт в Vue 3?", correct, wrong, code=code, code_lang="vue")


@family("vue.next_tick", "vue", 4, "Асинхронное обновление DOM и nextTick")
def _(rng):
    a = rng.randint(0, 50)
    steps = [rng.randint(1, 9) for _ in range(rng.randint(1, 3))]
    b = a + sum(steps)
    name = rng.choice(["count", "total", "page"])
    code = (
        "<script setup>\n"
        "import { ref, nextTick } from 'vue'\n\n"
        f"const {name} = ref({a})\n"
        "const el = ref(null)\n\n"
        "async function onClick() {\n"
        + "".join(f"  {name}.value += {s}\n" for s in steps)
        + "  console.log(el.value.textContent)\n"
        "  await nextTick()\n"
        "  console.log(el.value.textContent)\n"
        "}\n"
        "</script>\n\n"
        "<template>\n"
        f'  <p ref="el">{{{{ {name} }}}}</p>\n'
        '  <button @click="onClick">+</button>\n'
        "</template>"
    )
    return text(
        "Что выведут два `console.log` после нажатия кнопки? Введите через пробел.",
        f"{a} {b}",
        code=code,
        code_lang="vue",
        normalize="ci",
    )


@family("vue.watch_batching", "vue", 5, "watch: группировка изменений за тик и immediate")
def _(rng):
    groups = rng.randint(1, 3)
    immediate = rng.random() < 0.5
    who = rng.choice(NAMES)
    lines, value = [], ""
    for g in range(groups):
        for _ in range(rng.randint(1, 3)):
            value += who[len(value) % len(who)]
            lines.append(f"  query.value = '{value}'")
        if g < groups - 1:
            lines.append("  await nextTick()")
    code = (
        "<script setup>\n"
        "import { ref, watch, nextTick } from 'vue'\n\n"
        "const query = ref('')\n"
        "let calls = 0\n"
        f"watch(query, () => {{\n  calls++\n}}{', { immediate: true }' if immediate else ''})\n\n"
        "async function update() {\n" + "\n".join(lines) + "\n}\n"
        "</script>"
    )
    return number(
        "Чему будет равно `calls` после завершения `update()` и следующего обновления DOM?",
        groups + immediate,
        code=code,
        code_lang="vue",
    )
