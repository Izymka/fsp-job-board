"""Сборка бенчмарка подбора: популяция, потребности, прогоны систем и пул пар для разметки.

Методика — пулинг TREC: для каждой потребности размечается объединение top-10 всех систем.
Дополнительно в пул добавляются:
* случайные допустимые кандидаты вне пула — оценка того, сколько релевантных системы упустили;
* контрольные пары (кандидат другой специализации) — проверка внимательности асессоров:
  правильный ответ 0.

Артефакты (`ml/bench/data/`): needs.jsonl, candidates.jsonl, pairs.jsonl, runs.json, truth.jsonl.
Скрытая истина (truth.jsonl) асессорам не показывается и используется только как третий,
независимый источник эталона для синтетических потребностей.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import random
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import yaml

from ..catalog import DATA_DIR, get_catalog
from ..matching.scoring import Need
from ..nlp.embed import HashingEmbedder
from ..nlp.vacancy import parse_need
from ..validation import matching as vm
from ..validation.assessment import make_true_bank
from ..validation.population import TODAY, make_candidates, make_needs, true_relevance
from . import systems as S
from .dossier import render_candidate, render_need

BENCH_DIR = Path(__file__).resolve().parents[2] / "bench"
DATA = BENCH_DIR / "data"
POOL_DEPTH = 10
N_RANDOM = 4
N_CONTROL = 2


def pair_id(need_id: str, cand_id: str) -> str:
    return hashlib.sha1(f"{need_id}|{cand_id}".encode()).hexdigest()[:12]


def alias(cand_id: str) -> str:
    return "K-" + str(int(hashlib.sha1(cand_id.encode()).hexdigest(), 16) % 9000 + 1000)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _percentiles(feats) -> dict[str, float]:
    by_cat: dict[tuple, list[float]] = {}
    for f in feats:
        if f.grade and f.theta is not None:
            by_cat.setdefault((f.specialization, f.grade), []).append(f.theta)
    for v in by_cat.values():
        v.sort()
    out = {}
    for f in feats:
        peers = by_cat.get((f.specialization, f.grade))
        if f.theta is not None and peers and len(peers) >= 5:
            out[f.id] = float(np.searchsorted(peers, f.theta, side="right")) / len(peers)
    return out


def _to_need(pn, text: str, industry: str | None) -> Need:
    emb = HashingEmbedder()
    return Need(
        specialization=pn.specialization,
        grade=pn.grade or "middle",
        skills=dict(pn.skills),
        salary_from=pn.salary_from,
        salary_to=pn.salary_to,
        work_format=pn.work_format,
        industry=industry,
        text=text,
        embedding=emb.encode([text])[0],
    )


def make_bench_needs(n_synthetic: int) -> tuple[list[S.BenchNeed], dict]:
    """Синтетические потребности (есть скрытая истина) + реальные описания вакансий из data/vacancies.yaml."""
    cat = get_catalog()
    out: list[S.BenchNeed] = []
    true_needs = {}
    for tn in make_needs(n_synthetic):
        title = f"{cat.specializations[tn.spec].title} ({cat.grade(tn.grade).name})"
        pn = parse_need(tn.text, title)
        out.append(
            S.BenchNeed(
                id=tn.id,
                source="synthetic",
                title=title,
                text=render_need(title, tn.text),
                need=_to_need(pn, tn.text, tn.industry),
                meta={"true_spec": tn.spec, "true_grade": tn.grade},
            )
        )
        true_needs[tn.id] = tn
    raw = yaml.safe_load((DATA_DIR / "vacancies.yaml").read_text(encoding="utf-8"))["vacancies"]
    for v in raw:
        pn = parse_need(v["text"], v["title"])
        out.append(
            S.BenchNeed(
                id="v-" + v["id"],
                source="vacancy",
                title=v["title"],
                text=render_need(v["title"], v["text"], v.get("company")),
                need=_to_need(pn, v["text"], v.get("industry")),
                meta={"true_spec": v["expected"]["specialization"], "true_grade": v["expected"]["grade"]},
            )
        )
    return out, true_needs


def build_systems(corpus: S.Corpus, needs: list[S.BenchNeed], neural: bool = True) -> dict[str, S.Ranker]:
    systems: dict[str, S.Ranker] = {
        "ours": S.ours(corpus, TODAY, version=1),
        "bm25": S.bm25(corpus),
        "test_only": S.test_only(corpus),
        "random": S.random_in_category(corpus),
    }
    if not neural:
        return systems
    try:
        t = time.time()
        frida = S.dense(corpus, S.DenseEncoder("ai-forever/FRIDA"), needs)
        _log(f"  FRIDA: {time.time() - t:.0f} с")
        t = time.time()
        qwen = S.dense(corpus, S.DenseEncoder("Qwen/Qwen3-Embedding-0.6B"), needs)
        _log(f"  Qwen3-Embedding: {time.time() - t:.0f} с")
    except Exception as e:  # нет пакета/весов — бенчмарк работает без нейросетевых бейзлайнов
        _log(f"  нейросетевые бейзлайны недоступны: {e}")
        return systems
    systems["dense_frida"] = frida
    systems["dense_qwen3"] = qwen
    systems["hybrid_rrf"] = S.rrf(corpus, systems["bm25"], frida)
    try:
        ce = S.CrossEncoderReranker()
        systems["rerank_bge"] = S.rerank(corpus, systems["hybrid_rrf"], ce)
    except Exception as e:
        _log(f"  кросс-энкодер недоступен: {e}")
    return systems


def build(
    n_candidates: int = 1000,
    n_synthetic: int = 30,
    neural: bool = True,
    out: Path = DATA,
    prepared: tuple | None = None,
) -> dict:
    """prepared = (кандидаты-истина, наблюдаемые признаки, вакансии BenchNeed, {need_id: TrueNeed}) —
    готовая популяция (реалистичный бенчмарк); иначе генерируется синтетическая."""
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    if prepared is None:
        _log("Популяция и онбординг-тест…")
        cands = make_candidates(n_candidates, stuffing_rate=0.3)
        feats = vm.observe(cands, make_true_bank(), legacy=True).features
        needs, true_needs = make_bench_needs(n_synthetic)
    else:
        cands, feats, needs, true_needs = prepared
        n_candidates, n_synthetic = len(cands), len(true_needs)
    pct = _percentiles(feats)
    texts = [render_candidate(f, TODAY, alias=alias(f.id), percentile=pct.get(f.id)) for f in feats]
    corpus = S.Corpus(feats, texts)
    # состояние для add-system / distill без повторной генерации
    with (out / "state.pkl").open("wb") as fh:
        pickle.dump({"feats": feats, "needs": needs}, fh)

    _log("Прогоны систем…")
    systems = build_systems(corpus, needs, neural=neural)
    runs: dict[str, dict[str, list[str]]] = {}
    for name, ranker in systems.items():
        t = time.time()
        runs[name] = {bn.id: ranker(bn) for bn in needs}
        _log(f"  {name}: {time.time() - t:.1f} с")

    _log("Пул пар…")
    rng = random.Random(2026)
    pairs = []
    for bn in needs:
        pooled: dict[str, set[str]] = {}
        for name, run in runs.items():
            for cid in run[bn.id][:POOL_DEPTH]:
                pooled.setdefault(cid, set()).add(name)
        for cid, by in sorted(pooled.items()):
            pairs.append(
                {
                    "pair_id": pair_id(bn.id, cid),
                    "need_id": bn.id,
                    "cand_id": cid,
                    "kind": "pooled",
                    "systems": sorted(by),
                }
            )
        rest = [corpus.ids[i] for i in S.eligible_idx(corpus, bn) if corpus.ids[i] not in pooled]
        for cid in rng.sample(rest, min(N_RANDOM, len(rest))):
            pairs.append(
                {
                    "pair_id": pair_id(bn.id, cid),
                    "need_id": bn.id,
                    "cand_id": cid,
                    "kind": "random",
                    "systems": [],
                }
            )
        spec = bn.meta["true_spec"]
        others = [f.id for f in corpus.feats if f.specialization != spec and f.search_status != "closed"]
        for cid in rng.sample(others, N_CONTROL):
            pairs.append(
                {
                    "pair_id": pair_id(bn.id, cid),
                    "need_id": bn.id,
                    "cand_id": cid,
                    "kind": "control",
                    "systems": [],
                }
            )

    # скрытая истина для синтетических потребностей — по всем кандидатам (разреженно: rel > 0)
    truth_rows = []
    for nid, tn in true_needs.items():
        for c in cands:
            r = true_relevance(c, tn)
            if r > 0:
                truth_rows.append({"need_id": nid, "cand_id": c.id, "rel": r})

    def dump(name: str, rows) -> None:
        with (out / name).open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump(
        "needs.jsonl",
        [
            {
                "need_id": bn.id,
                "source": bn.source,
                "title": bn.title,
                "text": bn.text,
                "parsed": {
                    "specialization": bn.need.specialization,
                    "grade": bn.need.grade,
                    "skills": bn.need.skills,
                },
                **bn.meta,
            }
            for bn in needs
        ],
    )
    dump(
        "candidates.jsonl",
        [{"cand_id": cid, "alias": alias(cid), "text": t} for cid, t in zip(corpus.ids, texts)],
    )
    dump("pairs.jsonl", pairs)
    dump("truth.jsonl", truth_rows)
    (out / "runs.json").write_text(json.dumps(runs, ensure_ascii=False), encoding="utf-8")
    meta = {
        "n_candidates": n_candidates,
        "n_needs": len(needs),
        "n_synthetic": n_synthetic,
        "systems": list(runs),
        "pool_depth": POOL_DEPTH,
        "n_pairs": len(pairs),
        "pairs_by_kind": {k: sum(p["kind"] == k for p in pairs) for k in ("pooled", "random", "control")},
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(json.dumps(meta, ensure_ascii=False))
    return meta


def load_state(out: Path = DATA, n_candidates: int = 1000, n_synthetic: int = 30):
    """Наблюдаемые признаки кандидатов и вакансии бенчмарка: из state.pkl, иначе регенерация."""
    if (out / "state.pkl").exists():
        with (out / "state.pkl").open("rb") as fh:
            st = pickle.load(fh)
        return st["feats"], st["needs"]
    cands = make_candidates(n_candidates, stuffing_rate=0.3)
    return vm.observe(cands, make_true_bank(), legacy=True).features, load_bench_needs(n_synthetic, out)


def load_bench_needs(n_synthetic: int = 30, out: Path = DATA) -> list[S.BenchNeed]:
    """Вакансии бенчмарка из сохранённых текстов (ровно то, что видели асессоры).

    Тексты синтетических вакансий в ранних сборках зависели от PYTHONHASHSEED, поэтому их нельзя
    перегенерировать — разбираем сохранённый текст. Отрасль, вилка и формат от порядка не зависят.
    """
    industry = {tn.id: tn.industry for tn in make_needs(n_synthetic)}
    raw = yaml.safe_load((DATA_DIR / "vacancies.yaml").read_text(encoding="utf-8"))["vacancies"]
    industry.update({"v-" + v["id"]: v.get("industry") for v in raw})
    out_needs = []
    for r in load_jsonl(out / "needs.jsonl"):
        body = r["text"].split("\n\n", 1)[1]
        pn = parse_need(body, r["title"])
        meta = {k: r[k] for k in ("true_spec", "true_grade") if k in r}
        out_needs.append(
            S.BenchNeed(
                r["need_id"],
                r["source"],
                r["title"],
                r["text"],
                _to_need(pn, body, industry.get(r["need_id"])),
                meta,
            )
        )
    return out_needs


def _hybrid(corpus: S.Corpus, version: int) -> S.Ranker:
    from ..matching.hybrid import rank_hybrid

    text = dict(zip(corpus.ids, corpus.texts))

    def run(bn: S.BenchNeed) -> list[str]:
        if not bn.need.specialization:
            return []
        need = replace(bn.need, text=bn.text)
        return [
            s.candidate_id
            for s in rank_hybrid(corpus.feats, need, TODAY, card_text=lambda f: text[f.id], version=version)
        ][: S.DEPTH]

    return run


LOCAL_SYSTEMS = {
    "ours_v4": lambda corpus: _hybrid(corpus, 1),  # гибрид на формуле v1
    "ours_v5": lambda corpus: S.ours(corpus, TODAY, version=5),
    "ours_v5_ce": lambda corpus: _hybrid(corpus, 5),  # гибрид на формуле v5
    "ours_v6": lambda corpus: S.ours(corpus, TODAY, version=6),
    "ours_v7": lambda corpus: S.ours(corpus, TODAY, version=7),
    "ours": lambda corpus: S.ours(corpus, TODAY, version=1),
    "ours_v2": lambda corpus: S.ours(corpus, TODAY, version=2),
}


def add_systems(names: list[str], n_candidates: int = 1000, n_synthetic: int = 30, out: Path = DATA) -> dict:
    """Добавляет прогоны новых систем к готовому бенчмарку и дописывает в пул только новые пары.

    Популяция и вакансии воспроизводятся детерминированно (те же seed), поэтому кандидаты и
    тексты совпадают с исходной сборкой. Новые пары помечаются `batch: "addN"` для доразметки.
    """
    feats, needs = load_state(out, n_candidates, n_synthetic)
    card = {r["cand_id"]: r["text"] for r in load_jsonl(out / "candidates.jsonl")}
    corpus = S.Corpus(feats, [card.get(f.id, "") for f in feats])
    runs = json.loads((out / "runs.json").read_text(encoding="utf-8"))
    pairs = load_jsonl(out / "pairs.jsonl")
    known = {p["pair_id"]: p for p in pairs}
    added = []
    for name in names:
        ranker = LOCAL_SYSTEMS[name](corpus)
        runs[name] = {bn.id: ranker(bn) for bn in needs}
        for bn in needs:
            for cid in runs[name][bn.id][:POOL_DEPTH]:
                pid = pair_id(bn.id, cid)
                if pid in known:
                    if name not in known[pid]["systems"]:
                        known[pid]["systems"] = sorted([*known[pid]["systems"], name])
                    continue
                row = {
                    "pair_id": pid,
                    "need_id": bn.id,
                    "cand_id": cid,
                    "kind": "pooled",
                    "systems": [name],
                    "added": True,
                }
                known[pid] = row
                pairs.append(row)
                added.append(row)
    (out / "runs.json").write_text(json.dumps(runs, ensure_ascii=False), encoding="utf-8")
    with (out / "pairs.jsonl").open("w", encoding="utf-8") as fh:
        for r in pairs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"systems": names, "new_pairs": len(added), "total_pairs": len(pairs)}


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
