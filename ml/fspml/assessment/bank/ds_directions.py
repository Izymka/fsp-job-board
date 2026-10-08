"""Семейства заданий направлений Data Science: компьютерное зрение, NLP, рекомендательные системы,
временные ряды. Входят в тест модулем, если кандидат выбрал направление или заявил технологию."""

from __future__ import annotations

import math
from collections import Counter

from ..items import family, number, single

# ------------------------------------------------------------------------------------------- CV


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _box(rng, lo=0, hi=60, size=(10, 40)):
    x, y = rng.randint(lo, hi), rng.randint(lo, hi)
    return (x, y, x + rng.randint(*size), y + rng.randint(*size))


@family("cv.conv_output", "cv", 2, "Размер выхода свёртки")
def _(rng):
    w = rng.choice([28, 32, 64, 96, 128, 224])
    k = rng.choice([3, 5, 7])
    s = rng.choice([1, 2])
    p = rng.choice([0, 1, 2, 3])
    out = (w + 2 * p - k) // s + 1
    q = (
        f"Вход {w}×{w}, свёртка с ядром {k}×{k}, шаг (stride) {s}, паддинг {p}. "
        "Какова ширина выходной карты признаков (floor((W + 2P − K) / S) + 1)?"
    )
    return number(q, out)


@family("cv.conv_params", "cv", 3, "Число параметров свёрточного слоя")
def _(rng):
    cin = rng.choice([1, 3, 16, 32, 64])
    cout = rng.choice([8, 16, 32, 64, 128])
    k = rng.choice([1, 3, 5])
    bias = rng.random() < 0.7
    n = (k * k * cin + (1 if bias else 0)) * cout
    q = (
        f"Свёрточный слой: {cin} входных канала(ов), {cout} фильтров, ядро {k}×{k}, "
        f"{'со смещением (bias)' if bias else 'без смещения (bias=False)'}. Сколько у слоя обучаемых параметров?"
    )
    return number(q, n)


@family("cv.iou", "cv", 3, "IoU двух рамок")
def _(rng):
    while True:
        a, b = _box(rng), _box(rng)
        v = _iou(a, b)
        if 0.05 < v < 0.95:
            break
    q = (
        f"Рамки заданы как (x1, y1, x2, y2): предсказанная {a}, истинная {b}. "
        "Найдите IoU (площадь пересечения / площадь объединения). Точность 0,01."
    )
    return number(q, round(v, 4), tolerance=0.01)


@family("cv.nms", "cv", 4, "Non-maximum suppression")
def _(rng):
    while True:
        base = _box(rng, 10, 30, (30, 40))
        boxes = [base] + [
            tuple(c + rng.randint(-8, 8) for c in base) if rng.random() < 0.6 else _box(rng, 40, 90, (20, 35))
            for _ in range(rng.randint(4, 5))
        ]
        boxes = [(x1, y1, max(x2, x1 + 5), max(y2, y1 + 5)) for x1, y1, x2, y2 in boxes]
        scores = rng.sample([x / 100 for x in range(50, 100, 3)], len(boxes))
        thr = rng.choice([0.3, 0.5])
        order = sorted(range(len(boxes)), key=lambda i: -scores[i])
        keep: list[int] = []
        for i in order:
            if all(_iou(boxes[i], boxes[j]) <= thr for j in keep):
                keep.append(i)
        ious = [_iou(boxes[i], boxes[j]) for i in range(len(boxes)) for j in range(i)]
        if all(abs(x - thr) > 0.03 for x in ious):  # без пограничных случаев
            break
    listing = "; ".join(f"{b} — {s:.2f}" for b, s in zip(boxes, scores))
    q = (
        f"Детектор вернул рамки (x1, y1, x2, y2) — уверенность: {listing}. Применяется NMS с порогом IoU {thr}: "
        "рамки берутся по убыванию уверенности, рамка отбрасывается, если её IoU с уже оставленной больше порога. "
        "Сколько рамок останется?"
    )
    return number(q, len(keep))


@family("cv.augment", "cv", 2, "Аугментации и их уместность")
def _(rng):
    cases = [
        (
            "распознавание рукописных цифр",
            "Горизонтальное отражение: «2» и «5» превращаются в другие символы",
        ),
        (
            "классификация сигналов светофора по цвету",
            "Сильное изменение оттенка (hue): красный станет зелёным",
        ),
        (
            "детекция пешеходов с камеры автомобиля",
            "Вертикальное отражение: люди вверх ногами не встречаются",
        ),
        (
            "классификация рентгеновских снимков на «левое/правое лёгкое»",
            "Горизонтальное отражение меняет метку",
        ),
    ]
    task, a = rng.choice(cases)
    return single(
        rng,
        f"Задача: {task}. Какая аугментация вредна и почему?",
        a,
        [c[1] for c in cases if c[1] != a] + ["Небольшой случайный кроп: он всегда вреден"],
    )


@family("cv.split", "cv", 3, "Валидация в задачах зрения")
def _(rng):
    cases = [
        (
            "Кадры нарезаны из 40 видео матчей с шагом в секунду и случайно разбиты на train и test",
            "Почти одинаковые соседние кадры одного видео попадают в обе выборки — делить по видео",
        ),
        (
            "Снимки МРТ 300 пациентов (по 20 срезов на пациента) случайно разбиты по срезам",
            "Срезы одного пациента в train и test — делить по пациентам",
        ),
        (
            "Датасет собран из интернета, в нём много копий одной фотографии с разной обрезкой",
            "Дубликаты и почти-дубликаты нужно найти (perceptual hash, эмбеддинги) и держать в одной выборке",
        ),
        (
            "Модель обучена на фото с камер одного склада, в продакшене — другие склады",
            "Отложенная выборка должна быть с других складов (сдвиг домена)",
        ),
    ]
    sit, a = rng.choice(cases)
    return single(
        rng, f"{sit}. В чём проблема оценки?", a, [c[1] for c in cases if c[1] != a] + ["Проблемы нет"]
    )


@family("cv.precision_recall", "cv", 4, "Precision и recall детектора")
def _(rng):
    n_gt = rng.randint(4, 8)
    n_pred = rng.randint(5, 9)
    tp_flags = [rng.random() < 0.6 for _ in range(n_pred)]
    while sum(tp_flags) > n_gt or sum(tp_flags) == 0:
        tp_flags = [rng.random() < 0.6 for _ in range(n_pred)]
    k = rng.randint(3, n_pred)
    tp = sum(tp_flags[:k])
    metric = rng.choice(["precision", "recall"])
    val = tp / k if metric == "precision" else tp / n_gt
    marks = ", ".join("TP" if f else "FP" for f in tp_flags)
    q = (
        f"На изображении {n_gt} объектов. Детекции по убыванию уверенности (сопоставление с IoU ≥ 0,5): {marks}. "
        f"Найдите {metric} по первым {k} детекциям. Точность 0,01."
    )
    return number(q, round(val, 4), tolerance=0.01)


# ------------------------------------------------------------------------------------------ NLP

CORPUS_WORDS = ["матч", "гол", "тренер", "сезон", "клуб", "игрок", "судья", "победа", "команда"]


@family("nlp.tfidf", "nlp", 3, "TF-IDF")
def _(rng):
    while True:
        docs = [rng.choices(CORPUS_WORDS[:6], k=rng.randint(4, 6)) for _ in range(rng.randint(3, 4))]
        word = rng.choice(docs[0])
        df = sum(word in d for d in docs)
        if df < len(docs):
            break
    tf = docs[0].count(word) / len(docs[0])
    idf = math.log(len(docs) / df)
    listing = "; ".join(f"d{i + 1}: «{' '.join(d)}»" for i, d in enumerate(docs))
    q = (
        f"Корпус: {listing}. Найдите TF-IDF слова «{word}» в d1, если TF = доля слова в документе, "
        "IDF = ln(N / df), где df — число документов со словом. Точность 0,01."
    )
    return number(q, round(tf * idf, 4), tolerance=0.01)


@family("nlp.ngrams", "nlp", 1, "N-граммы")
def _(rng):
    tokens = rng.choices(CORPUS_WORDS[:5], k=rng.randint(6, 9))
    n = rng.choice([2, 3])
    grams = [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
    unique = rng.random() < 0.6
    q = (
        f"Текст из токенов: «{' '.join(tokens)}». Сколько {'различных ' if unique else ''}"
        f"{'биграмм' if n == 2 else 'триграмм'} в нём{' (с учётом повторов)' if not unique else ''}?"
    )
    return number(q, len(set(grams)) if unique else len(grams))


@family("nlp.bleu_unigram", "nlp", 3, "BLEU: модифицированная точность по униграммам")
def _(rng):
    ref = rng.sample(CORPUS_WORDS, 5)
    cand = rng.choices(ref[:3] + rng.sample(CORPUS_WORDS, 2), k=rng.randint(4, 6))
    rc = Counter(ref)
    clipped = sum(min(c, rc[w]) for w, c in Counter(cand).items())
    q = (
        f"Эталон: «{' '.join(ref)}». Перевод модели: «{' '.join(cand)}». Найдите модифицированную точность по "
        "униграммам, как в BLEU: число слов перевода, совпавших с эталоном (каждое слово засчитывается не больше раз, "
        "чем встречается в эталоне), делённое на длину перевода. Точность 0,01."
    )
    return number(q, round(clipped / len(cand), 4), tolerance=0.01)


@family("nlp.cosine_bow", "nlp", 2, "Косинусное сходство мешков слов")
def _(rng):
    while True:
        a = rng.choices(CORPUS_WORDS[:5], k=rng.randint(3, 5))
        b = rng.choices(CORPUS_WORDS[:5], k=rng.randint(3, 5))
        ca, cb = Counter(a), Counter(b)
        dot = sum(ca[w] * cb[w] for w in ca)
        if dot:
            break
    cos = dot / (math.sqrt(sum(v * v for v in ca.values())) * math.sqrt(sum(v * v for v in cb.values())))
    q = (
        f"Тексты «{' '.join(a)}» и «{' '.join(b)}» представлены векторами частот слов (bag of words). "
        "Найдите косинусное сходство. Точность 0,01."
    )
    return number(q, round(cos, 4), tolerance=0.01)


@family("nlp.edit_distance", "nlp", 3, "Расстояние Левенштейна")
def _(rng):
    pairs = [
        ("гол", "голы"),
        ("тренер", "тренировка"),
        ("судья", "судьи"),
        ("матч", "мяч"),
        ("клуб", "кубок"),
        ("сезон", "сезоны"),
        ("игрок", "игра"),
        ("команда", "комната"),
    ]
    a, b = rng.choice(pairs)
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (ca != cb))
    q = f"Найдите расстояние Левенштейна между «{a}» и «{b}» (вставка, удаление, замена — по 1)."
    return number(q, d[-1])


@family("nlp.task_model", "nlp", 2, "Постановка задач NLP")
def _(rng):
    cases = [
        ("выделить в отчёте о матче имена игроков и названия клубов", "Классификация токенов (NER)"),
        ("определить тональность отзыва о приложении", "Классификация текста целиком"),
        (
            "сократить длинный отчёт до трёх предложений своими словами",
            "Генерация seq2seq (абстрактивная суммаризация)",
        ),
        (
            "найти в базе знаний ответы, близкие по смыслу к вопросу",
            "Семантический поиск по эмбеддингам (bi-encoder)",
        ),
        (
            "переранжировать 50 найденных кандидатов по релевантности запросу",
            "Кросс-энкодер, оценивающий пару «запрос–документ»",
        ),
    ]
    need, a = rng.choice(cases)
    return single(rng, f"Нужно {need}. Какая постановка подходит?", a, [c[1] for c in cases if c[1] != a])


@family("nlp.attention", "nlp", 4, "Self-attention: вычисления и параметры")
def _(rng):
    n = rng.choice([128, 256, 512, 1024])
    h = rng.choice([4, 8, 12, 16])
    d = h * rng.choice([32, 64])
    if rng.random() < 0.5:
        q = (
            f"Слой multi-head self-attention: длина последовательности {n}, {h} голов. Сколько чисел в матрицах "
            "весов внимания (softmax(QKᵀ)) всех голов для одного примера?"
        )
        return number(q, h * n * n)
    q = (
        f"Слой multi-head self-attention с размерностью модели d = {d} и {h} головами: проекции Q, K, V и выходная "
        "проекция — матрицы d×d со смещениями. Сколько у слоя параметров?"
    )
    return number(q, 4 * (d * d + d))


# --------------------------------------------------------------------------------------- RecSys


def _dcg(rels: list[int]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


@family("rec.precision_k", "recsys", 2, "Precision@k и recall@k")
def _(rng):
    items = rng.sample(range(1, 30), 10)
    relevant = set(rng.sample(items, rng.randint(2, 5))) | set(rng.sample(range(30, 40), rng.randint(0, 2)))
    k = rng.choice([3, 5])
    hits = sum(i in relevant for i in items[:k])
    metric = rng.choice(["precision", "recall"])
    val = hits / k if metric == "precision" else hits / len(relevant)
    q = (
        f"Рекомендации пользователю по порядку: {items}. Релевантные пользователю товары: {sorted(relevant)}. "
        f"Найдите {metric}@{k}. Точность 0,01."
    )
    return number(q, round(val, 4), tolerance=0.01)


@family("rec.ndcg", "recsys", 4, "NDCG@k")
def _(rng):
    k = rng.choice([4, 5])
    while True:
        rels = [rng.choice([0, 0, 1, 2, 3]) for _ in range(k)]
        if any(rels):
            break
    ndcg = _dcg(rels) / _dcg(sorted(rels, reverse=True))
    q = (
        f"Оценки релевантности рекомендаций на позициях 1–{k}: {rels}. Найдите NDCG@{k}, если "
        "DCG = Σ rel_i / log₂(i + 1) по позициям i = 1..k, а идеальный DCG считается по тем же оценкам, "
        "отсортированным по убыванию. Точность 0,01."
    )
    return number(q, round(ndcg, 4), tolerance=0.01)


@family("rec.mrr", "recsys", 3, "Mean reciprocal rank")
def _(rng):
    ranks = [rng.choice([1, 2, 3, 4, 5, None]) for _ in range(rng.randint(3, 5))]
    if all(r is None for r in ranks):
        ranks[0] = 2
    mrr = sum(1 / r for r in ranks if r) / len(ranks)
    desc = ", ".join(
        f"у пользователя {i + 1} — {'на позиции ' + str(r) if r else 'нет в выдаче'}"
        for i, r in enumerate(ranks)
    )
    q = f"Первая релевантная рекомендация: {desc}. Найдите MRR. Точность 0,01."
    return number(q, round(mrr, 4), tolerance=0.01)


@family("rec.item_cosine", "recsys", 3, "Item-based: косинусное сходство товаров")
def _(rng):
    users = rng.randint(4, 5)
    while True:
        a = [rng.choice([0, 0, 1, 3, 4, 5]) for _ in range(users)]
        b = [rng.choice([0, 0, 1, 3, 4, 5]) for _ in range(users)]
        if any(x and y for x, y in zip(a, b)):
            break
    cos = sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )
    q = (
        f"Оценки {users} пользователей (0 — не оценивал): товар A — {a}, товар B — {b}. "
        "Найдите косинусное сходство векторов товаров. Точность 0,01."
    )
    return number(q, round(cos, 4), tolerance=0.01)


@family("rec.cold_start", "recsys", 2, "Холодный старт и смещения рекомендаций")
def _(rng):
    cases = [
        (
            "Новый пользователь без истории",
            "Популярное в сегменте и короткий опрос предпочтений при регистрации",
        ),
        (
            "Новый товар без взаимодействий",
            "Контентные признаки (категория, описание, эмбеддинги) и квота показов на исследование",
        ),
        (
            "Рекомендатель показывает только уже популярные товары, и они становятся ещё популярнее",
            "Петля обратной связи: исследование (exploration), штраф за популярность, учёт позиции показа",
        ),
        (
            "Офлайн-метрики выросли, а в A/B-тесте выручка не изменилась",
            "Офлайн-метрика не отражает цель: проверить связь с бизнес-метрикой и смещение логов",
        ),
    ]
    sit, a = rng.choice(cases)
    return single(rng, f"{sit}. Что делать?", a, [c[1] for c in cases if c[1] != a])


@family("rec.implicit", "recsys", 3, "Неявная обратная связь")
def _(rng):
    cases = [
        (
            "Есть только просмотры и покупки, оценок нет. Что считать отрицательным примером?",
            "Непросмотренное — не обязательно «не нравится»: сэмплировать негативы и взвешивать уверенность",
        ),
        (
            "Товар на первой позиции кликают чаще, чем на десятой, при той же релевантности. Как учитывать при обучении?",
            "Поправка на смещение позиции (position bias) — например, веса обратной склонности (IPS)",
        ),
        (
            "Какую метрику выбрать, если важно, чтобы релевантное было в самом верху короткой выдачи?",
            "NDCG@k или MRR — они учитывают позицию",
        ),
    ]
    q, a = rng.choice(cases)
    return single(rng, q, a, [c[1] for c in cases if c[1] != a] + ["Accuracy по всем товарам каталога"])


# --------------------------------------------------------------------------------- Time series


@family("ts.moving_average", "timeseries", 1, "Скользящее среднее")
def _(rng):
    series = [rng.randint(80, 140) for _ in range(rng.randint(7, 9))]
    k = rng.choice([3, 4, 5])
    f = sum(series[-k:]) / k
    q = f"Продажи по дням: {series}. Прогноз на завтра — среднее последних {k} дней. Чему он равен? Точность 0,01."
    return number(q, round(f, 4), tolerance=0.01)


@family("ts.exp_smoothing", "timeseries", 3, "Простое экспоненциальное сглаживание")
def _(rng):
    series = [rng.randint(20, 60) for _ in range(rng.randint(4, 5))]
    alpha = rng.choice([0.2, 0.3, 0.5])
    level = series[0]
    for y in series[1:]:
        level = alpha * y + (1 - alpha) * level
    q = (
        f"Ряд: {series}. Простое экспоненциальное сглаживание с α = {alpha}, начальный уровень — первое значение; "
        "уровень обновляется как ℓ = α·y + (1 − α)·ℓ для каждого следующего значения. Каков прогноз на следующий шаг? "
        "Точность 0,01."
    )
    return number(q, round(level, 4), tolerance=0.01)


@family("ts.mape", "timeseries", 2, "MAPE")
def _(rng):
    actual = [rng.randint(50, 200) for _ in range(4)]
    pred = [a + rng.randint(-30, 30) for a in actual]
    mape = sum(abs(a - p) / a for a, p in zip(actual, pred)) / len(actual) * 100
    q = f"Факт: {actual}, прогноз: {pred}. Найдите MAPE (%). Точность 0,1."
    return number(q, round(mape, 3), tolerance=0.1)


@family("ts.seasonal_naive", "timeseries", 2, "Сезонный наивный прогноз")
def _(rng):
    days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    week1 = [rng.randint(50, 120) for _ in range(7)]
    week2 = [v + rng.randint(-10, 10) for v in week1]
    h = rng.randint(1, 7)
    q = (
        f"Посещаемость фитнес-клуба за две недели (пн–вс): {week1} и {week2}. Сезонный наивный прогноз "
        f"(значение того же дня прошлой недели): сколько посетителей ожидать в {days[h - 1]} третьей недели?"
    )
    return number(q, week2[h - 1])


@family("ts.validation", "timeseries", 2, "Валидация прогнозов")
def _(rng):
    cases = [
        (
            "Как оценивать модель прогноза спроса?",
            "Скользящее окно по времени: обучение на прошлом, проверка на следующем периоде",
        ),
        (
            "Признак «средние продажи за неделю» посчитан по окну, включающему день прогноза",
            "Утечка из будущего: окно должно заканчиваться до момента прогноза",
        ),
        (
            "Модель хорошо прогнозирует на 1 день вперёд, а закупки делаются на 14 дней",
            "Оценивать на нужном горизонте: ошибка растёт с горизонтом",
        ),
        (
            "В ряду продаж есть дни, когда товара не было на складе",
            "Это цензурированный спрос: продажи ≠ спрос, такие дни помечать или восстанавливать",
        ),
    ]
    sit, a = rng.choice(cases)
    return single(
        rng, f"{sit}. Как правильно?", a, [c[1] for c in cases if c[1] != a] + ["Случайный KFold по дням"]
    )


@family("ts.autocorr", "timeseries", 4, "Автокорреляция")
def _(rng):
    while True:
        y = [rng.randint(1, 9) for _ in range(rng.randint(6, 8))]
        m = sum(y) / len(y)
        den = sum((v - m) ** 2 for v in y)
        if den:
            break
    lag = rng.choice([1, 2])
    num = sum((y[t] - m) * (y[t - lag] - m) for t in range(lag, len(y)))
    q = (
        f"Ряд: {y}. Найдите выборочную автокорреляцию с лагом {lag}: "
        f"r = Σ(y_t − ȳ)(y_(t−{lag}) − ȳ) / Σ(y_t − ȳ)². Точность 0,02."
    )
    return number(q, round(num / den, 4), tolerance=0.02)


@family("ts.differencing", "timeseries", 3, "Разности и стационарность")
def _(rng):
    m = rng.choice([4, 7, 12])
    series = [rng.randint(10, 50) for _ in range(m + rng.randint(2, 4))]
    t = rng.randint(m, len(series) - 1)
    seasonal = rng.random() < 0.5
    val = series[t] - series[t - m] if seasonal else series[t] - series[t - 1]
    kind = f"сезонной разности с периодом {m}" if seasonal else "первой разности"
    q = (
        f"Ряд (нумерация с 1): {series}. Чему равно значение {kind} в точке t = {t + 1} "
        f"({'y_t − y_(t−' + str(m) + ')' if seasonal else 'y_t − y_(t−1)'})?"
    )
    return number(q, val)
