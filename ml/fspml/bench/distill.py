"""Дистилляция v3: обучение LambdaMART на метках асессора с перекрёстной проверкой по вакансиям.

Прогон `ours_v3` в бенчмарке строится **вне выборки**: вакансии делятся на 5 частей, и выдача
каждой вакансии считается моделью, которая эту вакансию не видела. Учитель — один асессор
(по умолчанию claude-opus-5-5); честная оценка — по остальным источникам эталона (другой судья,
скрытая истина, эксперты), на которых модель не училась.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from ..matching import ltr
from ..matching.scoring import eligible
from ..validation.population import TODAY
from . import systems as S
from .build import DATA, POOL_DEPTH, load_jsonl, load_state, pair_id

N_FOLDS = 5


def _dataset(n_candidates: int = 1000, data: Path = DATA):
    feats, needs = load_state(data, n_candidates)
    from ..catalog import get_catalog

    cat = get_catalog()
    rows: dict[str, list[tuple[str, dict]]] = {}
    for bn in needs:
        out = []
        for f in feats:
            ok, adj = eligible(f, bn.need, cat)
            if ok:
                out.append((f.id, ltr.features(f, bn.need, TODAY, adjacent=adj, catalog=cat)))
        rows[bn.id] = out
    return needs, rows


def run(teacher: str = "claude-opus-5-5", data: Path = DATA, save_model: bool = True) -> dict:  # noqa: C901
    labels = {
        r["pair_id"]: r["label"] for r in load_jsonl(data / "judgments_llm.jsonl") if r["model"] == teacher
    }
    needs, rows = _dataset(data=data)
    need_ids = [bn.id for bn in needs]
    rng = np.random.default_rng(0)
    order = rng.permutation(len(need_ids))
    fold_of = {need_ids[i]: k % N_FOLDS for k, i in enumerate(order)}

    def train_on(ids: list[str]):
        X, y, groups = [], [], []
        for nid in ids:
            lab = [
                (feat, labels[pair_id(nid, cid)]) for cid, feat in rows[nid] if pair_id(nid, cid) in labels
            ]
            if len(lab) < 2:
                continue
            X += [f for f, _ in lab]
            y += [l for _, l in lab]
            groups.append(len(lab))
        return ltr.train(ltr.matrix(X), np.array(y), groups), len(y)

    run_v3: dict[str, list[str]] = {}
    for k in range(N_FOLDS):
        train_ids = [n for n in need_ids if fold_of[n] != k]
        model, n_train = train_on(train_ids)
        for nid in need_ids:
            if fold_of[nid] != k or not rows[nid]:
                run_v3.setdefault(nid, [])
                continue
            ids = [cid for cid, _ in rows[nid]]
            scores = model.predict(ltr.matrix([f for _, f in rows[nid]]))
            ranked = sorted(zip(ids, scores), key=lambda t: (-t[1], t[0]))
            run_v3[nid] = [cid for cid, _ in ranked][: S.DEPTH]
        print(f"  фолд {k + 1}/{N_FOLDS}: обучено на {n_train} парах", file=sys.stderr)

    # итоговая модель для продукта — на всех вакансиях
    final, n_all = train_on(need_ids)
    importance = dict(zip(ltr.FEATURE_NAMES, map(int, final.booster_.feature_importance("gain"))))
    if save_model:
        ltr.save(final)

    # прогон в бенчмарк + новые пары в пул для доразметки
    runs = json.loads((data / "runs.json").read_text(encoding="utf-8"))
    runs["ours_v3"] = run_v3
    (data / "runs.json").write_text(json.dumps(runs, ensure_ascii=False), encoding="utf-8")
    pairs = load_jsonl(data / "pairs.jsonl")
    known = {p["pair_id"]: p for p in pairs}
    new = 0
    for nid, run in run_v3.items():
        for cid in run[:POOL_DEPTH]:
            pid = pair_id(nid, cid)
            if pid in known:
                if "ours_v3" not in known[pid]["systems"]:
                    known[pid]["systems"] = sorted([*known[pid]["systems"], "ours_v3"])
                continue
            row = {
                "pair_id": pid,
                "need_id": nid,
                "cand_id": cid,
                "kind": "pooled",
                "systems": ["ours_v3"],
                "added": True,
            }
            known[pid] = row
            pairs.append(row)
            new += 1
    with (data / "pairs.jsonl").open("w", encoding="utf-8") as fh:
        for r in pairs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"teacher": teacher, "train_pairs": n_all, "new_pairs": new, "gain_importance": importance}
