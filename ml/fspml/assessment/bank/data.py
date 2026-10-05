"""Семейства заданий: pandas/NumPy, статистика и вероятность, машинное обучение."""

from __future__ import annotations

import math
import statistics as st
from fractions import Fraction

from ..items import family, number, single, text
from ._util import CITIES, NAMES, run_py

PREDICT = "Что выведет программа? Введите вывод."


def _df_literal(rng, n: int) -> tuple[str, list[dict]]:
    rows = [
        {
            "name": nm,
            "city": rng.choice(CITIES[:3]),
            "age": rng.randint(20, 45),
            "score": rng.choice([None, *range(50, 100, 5)])
            if rng.random() < 0.25
            else rng.randrange(50, 100, 5),
        }
        for nm in rng.sample(NAMES, n)
    ]
    lit = "pd.DataFrame([\n" + ",\n".join(f"    {r!r}" for r in rows) + "\n])"
    return lit, rows


# ------------------------------------------------------------------------------------ pandas/numpy


@family("pd.filter", "pandas", 1, "Фильтрация DataFrame")
def _(rng):
    lit, rows = _df_literal(rng, rng.randint(6, 8))
    age = rng.randint(25, 38)
    city = rng.choice(CITIES[:3])
    op = rng.choice(["&", "|"])
    code = (
        f"import pandas as pd\ndf = {lit}\nprint(len(df[(df['age'] > {age}) {op} (df['city'] == {city!r})]))"
    )
    return number(PREDICT, int(run_py(code)), code=code, code_lang="python")


@family("pd.nan", "pandas", 2, "Пропуски: mean, count, fillna")
def _(rng):
    vals = [rng.choice([None, 2, 4, 6, 8, 10]) for _ in range(rng.randint(5, 7))]
    if all(v is not None for v in vals):
        vals[0] = None
    if all(v is None for v in vals):
        vals[1] = 4
    fill = rng.randint(0, 3)
    expr = rng.choice(
        ["s.mean()", "s.count()", f"s.fillna({fill}).mean()", "s.isna().sum()", "len(s.dropna())"]
    )
    code = f"import pandas as pd\ns = pd.Series({vals!r}, dtype='float')\nprint(round({expr}, 2))"
    return number(PREDICT, float(run_py(code)), tolerance=0.01, code=code, code_lang="python")


@family("pd.groupby", "pandas", 2, "groupby и агрегаты")
def _(rng):
    lit, _rows = _df_literal(rng, rng.randint(7, 9))
    agg = rng.choice(["mean", "max", "count", "size"])
    code = (
        f"import pandas as pd\ndf = {lit}\n"
        f"g = df.groupby('city')['score'].{agg}()\n"
        "print(g.idxmax(), round(float(g.max()), 1))"
    )
    return text(
        PREDICT + " Формат — как печатает Python, например: `Москва 72.5`.",
        run_py(code),
        normalize="ci",
        code=code,
        code_lang="python",
    )


@family("pd.merge", "pandas", 3, "merge: число строк и дубликаты ключей")
def _(rng):
    left_keys = [rng.randint(1, 4) for _ in range(rng.randint(4, 6))]
    right_keys = [rng.randint(1, 5) for _ in range(rng.randint(3, 5))]
    how = rng.choice(["inner", "left", "outer"])
    code = (
        "import pandas as pd\n"
        f"a = pd.DataFrame({{'k': {left_keys!r}}})\n"
        f"b = pd.DataFrame({{'k': {right_keys!r}, 'v': range({len(right_keys)})}})\n"
        f"print(len(a.merge(b, on='k', how={how!r})))"
    )
    return number(PREDICT, int(run_py(code)), code=code, code_lang="python")


@family("np.broadcast", "pandas", 3, "NumPy: broadcasting и формы")
def _(rng):
    a = (rng.randint(2, 4), 1)
    b = (rng.randint(2, 5),)
    variant = rng.choice(["add", "sum0", "sum1", "reshape"])
    if variant == "add":
        expr = f"(np.ones({a}) + np.ones({b})).shape"
    elif variant == "sum0":
        expr = f"(np.ones({a}) * np.arange({b[0]})).sum(axis=0).shape"
    elif variant == "sum1":
        expr = f"(np.ones({a}) * np.arange({b[0]})).sum(axis=1)[0]"
    else:
        n = a[0] * b[0]
        expr = f"np.arange({n}).reshape({a[0]}, -1).T.shape"
    code = f"import numpy as np\nprint({expr})"
    return text(PREDICT, run_py(code), normalize="nospace", code=code, code_lang="python")


@family("pd.loc_iloc", "pandas", 4, "loc против iloc: границы срезов")
def _(rng):
    start = rng.randint(0, 3)
    n = rng.randint(6, 9)
    idx = list(range(start * 10, start * 10 + n * 10, 10))
    a, b = rng.sample(range(1, n - 1), 2)
    a, b = min(a, b), max(a, b)
    accessor = rng.choice(["loc", "iloc"])
    sl = f"{idx[a]}:{idx[b]}" if accessor == "loc" else f"{a}:{b}"
    code = f"import pandas as pd\ns = pd.Series(range({n}), index={idx!r})\nprint(s.{accessor}[{sl}].sum())"
    return number(PREDICT, int(run_py(code)), code=code, code_lang="python")


@family("pd.apply_transform", "pandas", 4, "transform, rank и оконные операции")
def _(rng):
    lit, _ = _df_literal(rng, rng.randint(6, 8))
    variant = rng.choice(["transform", "rolling", "cumsum"])
    if variant == "transform":
        body = (
            "df['m'] = df.groupby('city')['age'].transform('max')\nprint(int((df['age'] == df['m']).sum()))"
        )
    elif variant == "rolling":
        w = rng.randint(2, 3)
        body = f"print(int(df['age'].rolling({w}).sum().max()))"
    else:
        body = "print(int(df.sort_values('age')['age'].cumsum().iloc[2]))"
    code = f"import pandas as pd\ndf = {lit}\n{body}"
    return number(PREDICT, int(run_py(code)), code=code, code_lang="python")


# ------------------------------------------------------------------------------------- Statistics


@family("stat.descriptive", "statistics", 1, "Среднее, медиана, мода")
def _(rng):
    xs = [rng.randint(1, 20) for _ in range(rng.choice([5, 6, 7, 8]))]
    xs.append(rng.choice(xs))
    what = rng.choice(["median", "mean", "range"])
    if what == "median":
        ans, name = st.median(xs), "медиану"
    elif what == "mean":
        ans, name = st.mean(xs), "среднее арифметическое"
    else:
        ans, name = max(xs) - min(xs), "размах"
    return number(
        f"Найдите {name} выборки: {xs}. Ответ с точностью до 0,01.", round(float(ans), 2), tolerance=0.01
    )


@family("stat.probability", "statistics", 2, "Классическая вероятность")
def _(rng):
    variant = rng.choice(["dice_sum", "cards", "coins"])
    if variant == "dice_sum":
        s = rng.randint(4, 10)
        p = Fraction(sum(1 for a in range(1, 7) for b in range(1, 7) if a + b == s), 36)
        q = f"Бросают два честных кубика. Какова вероятность, что сумма равна {s}?"
    elif variant == "cards":
        n_red, n_blue = rng.randint(2, 6), rng.randint(2, 6)
        p = Fraction(n_red, n_red + n_blue) * Fraction(n_red - 1, n_red + n_blue - 1)
        q = f"В урне {n_red} красных и {n_blue} синих шаров. Достают два шара без возвращения. Какова вероятность, что оба красные?"
    else:
        n, k = rng.randint(3, 6), None
        k = rng.randint(1, n - 1)
        p = Fraction(math.comb(n, k), 2**n)
        q = f"Монету бросают {n} раз. Какова вероятность выпадения ровно {k} орлов?"
    return number(q + " Ответ — десятичная дробь с точностью до 0,001.", round(float(p), 4), tolerance=0.001)


@family("stat.variance", "statistics", 2, "Дисперсия и стандартное отклонение")
def _(rng):
    xs = [rng.randint(1, 12) for _ in range(rng.randint(4, 6))]
    kind = rng.choice(["population", "sample"])
    ans = st.pstdev(xs) if kind == "population" else st.stdev(xs)
    word = (
        "генеральной совокупности (делитель n)"
        if kind == "population"
        else "выборочное несмещённое (делитель n−1)"
    )
    return number(
        f"Найдите стандартное отклонение {word} для данных {xs}. Точность 0,01.",
        round(ans, 3),
        tolerance=0.011,
    )


@family("stat.bayes", "statistics", 3, "Формула Байеса")
def _(rng):
    prev = rng.choice([0.001, 0.005, 0.01, 0.02, 0.05])
    sens = rng.choice([0.9, 0.95, 0.99])
    spec = rng.choice([0.9, 0.95, 0.98, 0.99])
    post = sens * prev / (sens * prev + (1 - spec) * (1 - prev))
    q = (
        f"Заболевание встречается у {prev * 100:g}% людей. Тест выявляет больного с вероятностью {sens * 100:g}% "
        f"и даёт отрицательный результат у здорового с вероятностью {spec * 100:g}%. Тест положительный. "
        "Какова вероятность, что человек болен? Ответ в процентах, точность 0,5 п.п."
    )
    return number(q, round(post * 100, 2), tolerance=0.5)


@family("stat.pvalue", "statistics", 3, "Интерпретация p-value и доверительных интервалов")
def _(rng):
    p = rng.choice([0.003, 0.02, 0.04, 0.07, 0.3])
    alpha = rng.choice([0.01, 0.05])
    reject = p < alpha
    ans = "Отвергаем H0 на уровне значимости α" if reject else "Нет оснований отвергнуть H0 на уровне α"
    distractors = [
        "Отвергаем H0 на уровне значимости α" if not reject else "Нет оснований отвергнуть H0 на уровне α",
        f"H0 верна с вероятностью {p}",
        f"Эффект существует с вероятностью {1 - p:.3g}",
        "Принимаем H0 как доказанную",
    ]
    return single(
        rng, f"A/B-тест дал p-value = {p}, выбран α = {alpha}. Какой вывод корректен?", ans, distractors
    )


@family("stat.ab_z", "statistics", 4, "A/B-тест: z-статистика для конверсий")
def _(rng):
    n = rng.choice([1000, 2000, 5000])
    pa = rng.choice([0.10, 0.12, 0.15, 0.20])
    lift = rng.choice([0.01, 0.015, 0.02, 0.03])
    pb = pa + lift
    xa, xb = round(pa * n), round(pb * n)
    p_pool = (xa + xb) / (2 * n)
    se = math.sqrt(p_pool * (1 - p_pool) * (2 / n))
    z = (xb / n - xa / n) / se
    q = (
        f"Группа A: {xa} конверсий из {n}, группа B: {xb} из {n}. Посчитайте z-статистику двухвыборочного теста для долей "
        "с объединённой оценкой p (pooled). Точность 0,05."
    )
    return number(q, round(z, 3), tolerance=0.05)


@family("stat.multiple_testing", "statistics", 5, "Множественные сравнения")
def _(rng):
    m = rng.choice([5, 10, 20])
    alpha = rng.choice([0.05, 0.1])
    variant = rng.choice(["fwer", "bonf"])
    if variant == "fwer":
        ans = (1 - (1 - alpha) ** m) * 100
        q = f"Проводят {m} независимых тестов при α = {alpha}, все нулевые гипотезы верны. Какова вероятность (в %) хотя бы одного ложноположительного результата? Точность 0,5 п.п."
        return number(q, round(ans, 2), tolerance=0.5)
    ans = alpha / m
    q = f"Проводят {m} сравнений и хотят контролировать FWER на уровне {alpha} поправкой Бонферрони. Какой порог p-value использовать для каждого теста? Точность 0,0001."
    return number(q, round(ans, 5), tolerance=0.0001)


@family("stat.expectation", "statistics", 4, "Математическое ожидание")
def _(rng):
    variant = rng.choice(["geom", "lottery"])
    if variant == "geom":
        p = rng.choice([0.1, 0.2, 0.25, 0.5])
        q = f"Каждая попытка независимо успешна с вероятностью {p}. Сколько попыток в среднем потребуется до первого успеха (включая успешную)?"
        return number(q, round(1 / p, 3), tolerance=0.01)
    price = rng.choice([100, 200, 500])
    win = rng.choice([1000, 5000, 10000])
    pw = rng.choice([0.01, 0.02, 0.05])
    ev = pw * win - price
    q = f"Билет стоит {price} ₽, с вероятностью {pw} он выигрывает {win} ₽. Каков ожидаемый выигрыш с учётом стоимости билета (₽)?"
    return number(q, round(ev, 2), tolerance=0.01)


# --------------------------------------------------------------------------------------------- ML


@family("ml.task_type", "ml", 1, "Тип задачи машинного обучения")
def _(rng):
    cases = [
        ("предсказать, уйдёт ли клиент в следующем месяце", "Бинарная классификация"),
        ("спрогнозировать выручку магазина на завтра", "Регрессия"),
        ("разбить клиентов на группы без заранее известных меток", "Кластеризация"),
        ("определить тему обращения из 12 возможных", "Многоклассовая классификация"),
        ("найти подозрительные транзакции без размеченных примеров мошенничества", "Поиск аномалий"),
        ("упорядочить товары в выдаче по вероятности покупки", "Ранжирование"),
    ]
    need, ans = rng.choice(cases)
    return single(rng, f"К какому типу относится задача: {need}?", ans, [c[1] for c in cases if c[1] != ans])


@family("ml.metrics", "ml", 2, "Precision, recall, F1 по матрице ошибок")
def _(rng):
    tp, fp, fn, tn = rng.randint(10, 80), rng.randint(5, 40), rng.randint(5, 40), rng.randint(50, 200)
    metric = rng.choice(["precision", "recall", "f1", "accuracy"])
    p, r = tp / (tp + fp), tp / (tp + fn)
    val = {
        "precision": p,
        "recall": r,
        "f1": 2 * p * r / (p + r),
        "accuracy": (tp + tn) / (tp + fp + fn + tn),
    }[metric]
    q = f"Матрица ошибок: TP = {tp}, FP = {fp}, FN = {fn}, TN = {tn}. Найдите {metric}. Точность 0,005."
    return number(q, round(val, 4), tolerance=0.005)


@family("ml.fitting", "ml", 2, "Переобучение и недообучение")
def _(rng):
    tr = rng.choice([0.99, 0.97, 0.95])
    cases = [
        (
            f"Accuracy на train {tr}, на валидации {round(tr - rng.uniform(0.2, 0.3), 2)}",
            "Переобучение: усилить регуляризацию или упростить модель",
        ),
        (
            f"Accuracy на train {round(tr - 0.35, 2)}, на валидации {round(tr - 0.37, 2)} при сильном бейзлайне 0.85",
            "Недообучение: усложнить модель или добавить признаки",
        ),
        (
            f"Accuracy на train {tr}, на валидации {round(tr - 0.01, 2)}, а в продакшене резко хуже",
            "Сдвиг распределения или утечка данных в валидацию",
        ),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng,
        f"{sit}. Наиболее вероятный диагноз?",
        ans,
        [c[1] for c in cases if c[1] != ans] + ["Модель идеальна, ничего делать не нужно"],
    )


@family("ml.leakage", "ml", 3, "Утечки данных и валидация")
def _(rng):
    cases = [
        (
            "Нормализацию (StandardScaler) обучили на всём датасете до разбиения на train/test",
            "Утечка: статистики теста попали в обучение",
        ),
        (
            "Для временного ряда использовали случайный KFold",
            "Утечка из будущего: нужна валидация по времени",
        ),
        (
            "Признак «сумма возврата» используется для предсказания факта возврата заказа",
            "Утечка целевой переменной через признак",
        ),
        (
            "Один и тот же пользователь встречается и в train, и в test, а модель предсказывает поведение пользователя",
            "Нужен GroupKFold по пользователю",
        ),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng, f"{sit}. В чём проблема?", ans, [c[1] for c in cases if c[1] != ans] + ["Проблемы нет"]
    )


@family("ml.auc", "ml", 4, "ROC-AUC по ранжированию")
def _(rng):
    n_pos, n_neg = rng.randint(2, 4), rng.randint(3, 5)
    scores = rng.sample([x / 100 for x in range(5, 100, 5)], n_pos + n_neg)
    pos, neg = scores[:n_pos], scores[n_pos:]
    pairs = sum(1 for p in pos for n in neg if p > n)
    auc = pairs / (n_pos * n_neg)
    q = (
        f"Скоры модели для положительных объектов: {sorted(pos)}, для отрицательных: {sorted(neg)}. "
        "Найдите ROC-AUC (долю пар «положительный–отрицательный», где положительный получил больший скор). Точность 0,01."
    )
    return number(q, round(auc, 4), tolerance=0.01)


@family("ml.gradient_step", "ml", 4, "Шаг градиентного спуска")
def _(rng):
    xs = [rng.randint(1, 4) for _ in range(3)]
    w_true = rng.randint(1, 3)
    ys = [w_true * x + rng.choice([-1, 0, 1]) for x in xs]
    w0 = rng.choice([0, 0.5, 1])
    lr = rng.choice([0.01, 0.05, 0.1])
    grad = sum(2 * (w0 * x - y) * x for x, y in zip(xs, ys)) / len(xs)
    w1 = w0 - lr * grad
    q = (
        f"Модель y = w·x без смещения, функция потерь — MSE = (1/n)·Σ(w·xᵢ − yᵢ)². Данные (x, y): {list(zip(xs, ys))}. "
        f"Начальное w = {w0}, learning rate = {lr}. Каким станет w после одного шага градиентного спуска? Точность 0,01."
    )
    return number(q, round(w1, 4), tolerance=0.01)


@family("ml.gini", "ml", 5, "Решающие деревья: прирост информации по Джини")
def _(rng):
    l_pos, l_neg = rng.randint(0, 6), rng.randint(0, 6)
    r_pos, r_neg = rng.randint(0, 6), rng.randint(0, 6)
    if l_pos + l_neg == 0:
        l_pos = 1
    if r_pos + r_neg == 0:
        r_neg = 1

    def gini(p, n):
        t = p + n
        return 1 - (p / t) ** 2 - (n / t) ** 2

    tot_p, tot_n = l_pos + r_pos, l_neg + r_neg
    tot = tot_p + tot_n
    gain = (
        gini(tot_p, tot_n)
        - ((l_pos + l_neg) / tot) * gini(l_pos, l_neg)
        - ((r_pos + r_neg) / tot) * gini(r_pos, r_neg)
    )
    q = (
        f"В узле {tot_p} объектов класса 1 и {tot_n} класса 0. Разбиение даёт левый узел ({l_pos} класса 1, {l_neg} класса 0) "
        f"и правый ({r_pos} класса 1, {r_neg} класса 0). Найдите уменьшение неоднородности Джини (взвешенное по размерам узлов). Точность 0,005."
    )
    return number(q, round(gain, 4), tolerance=0.005)


@family("ml.kmeans", "ml", 4, "k-means: одна итерация")
def _(rng):
    pts = sorted(rng.sample(range(0, 30), 6))
    c1, c2 = rng.sample(pts, 2)
    c1, c2 = min(c1, c2), max(c1, c2)
    g1 = [p for p in pts if abs(p - c1) <= abs(p - c2)]
    g2 = [p for p in pts if abs(p - c1) > abs(p - c2)]
    target = rng.choice([1, 2])
    group = g1 if target == 1 else g2
    new = sum(group) / len(group)
    which = "первого" if target == 1 else "второго"
    q = (
        f"Одномерные точки: {pts}. Начальные центроиды: {c1} (первый) и {c2} (второй); при равенстве расстояний точка уходит к первому. "
        f"Где окажется центроид {which} кластера после одной итерации k-means? Точность 0,01."
    )
    return number(q, round(new, 4), tolerance=0.01)


@family("ml.regularization", "ml", 3, "Регуляризация и выбор модели")
def _(rng):
    cases = [
        (
            "Нужно, чтобы часть весов линейной модели стала ровно нулевой (отбор признаков)",
            "L1-регуляризация (Lasso)",
        ),
        ("Признаки сильно коррелированы, нужно стабилизировать веса без отбора", "L2-регуляризация (Ridge)"),
        ("Нейросеть переобучается, нужно случайно отключать нейроны при обучении", "Dropout"),
        ("Градиентный бустинг переобучается с ростом числа деревьев", "Ранняя остановка по валидации"),
    ]
    sit, ans = rng.choice(cases)
    return single(
        rng, f"{sit}. Что применить?", ans, [c[1] for c in cases if c[1] != ans] + ["Увеличить learning rate"]
    )


@family("ml.imbalance", "ml", 1, "Несбалансированные классы")
def _(rng):
    pos = rng.choice([0.5, 1, 2, 5])
    acc = 100 - pos
    q = (
        f"Мошеннические транзакции составляют {pos}% данных. Модель, всегда предсказывающая «не мошенничество», "
        "имеет какую accuracy (%)? Введите число."
    )
    return number(q, acc, tolerance=0.01)
