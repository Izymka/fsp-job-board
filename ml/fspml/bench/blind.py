"""Слепая разметка агентами (Claude, DeepSeek harness): пачки пар в Markdown → метки в JSONL.

Пачка содержит только рубрику, тексты вакансий и карточки кандидатов с идентификатором пары.
Какая система нашла пару, вид пары (пул / случайная / контрольная) и код механики асессору
не видны. Вакансия печатается один раз, под ней — её кандидаты в случайном порядке.

Метки агента: `ml/bench/blind/out/<assessor>/batch_XX.jsonl`, строка —
{"pair_id": "...", "label": 0-3, "rationale": "..."}. Импорт добавляет их в judgments_llm.jsonl
как ещё одну «модель» ансамбля (`model` = имя асессора).
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from .build import BENCH_DIR, DATA, load_jsonl
from .rubric import RUBRIC, RUBRIC_VERSION

BLIND = BENCH_DIR / "blind"


def export_batches(
    size: int = 100,
    data: Path = DATA,
    out: Path = BLIND / "batches",
    *,
    missing_for: str | None = None,
    prefix: str = "batch",
) -> list[Path]:
    """Пачки для слепой разметки. missing_for — только пары, которых нет у этого асессора (доразметка)."""
    needs = {r["need_id"]: r["text"] for r in load_jsonl(data / "needs.jsonl")}
    cands = {r["cand_id"]: r["text"] for r in load_jsonl(data / "candidates.jsonl")}
    by_need: dict[str, list[dict]] = defaultdict(list)
    done = (
        {r["pair_id"] for r in load_jsonl(data / "judgments_llm.jsonl") if r["model"] == missing_for}
        if missing_for
        else set()
    )
    for p in load_jsonl(data / "pairs.jsonl"):
        if p["pair_id"] not in done:
            by_need[p["need_id"]].append(p)
    rng = random.Random(11)
    need_ids = sorted(by_need)
    rng.shuffle(need_ids)
    # вакансии целиком, крупные режутся на части — чтобы пачки были примерно равны
    chunks: list[list[dict]] = []
    for nid in need_ids:
        items = by_need[nid][:]
        rng.shuffle(items)
        for i in range(0, len(items), size):
            chunks.append(items[i : i + size])
    batches: list[list[dict]] = []
    for ch in chunks:
        if batches and len(batches[-1]) + len(ch) <= size:
            batches[-1].extend(ch)
        else:
            batches.append(list(ch))
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob(f"{prefix}_*.md"):
        old.unlink()
    paths = []
    for bi, batch in enumerate(batches, 1):
        name = f"{prefix}_{bi:02d}"
        lines = [
            f"# Пачка {name}: {len(batch)} пар",
            "",
            f"Рубрика версии {RUBRIC_VERSION}. Оцените каждую пару по шкале 0–3.",
            "",
            "```text",
            RUBRIC.strip(),
            "```",
            "",
        ]
        cur = None
        for p in batch:
            if p["need_id"] != cur:
                cur = p["need_id"]
                lines += ["---", "", "## ВАКАНСИЯ", "", "```text", needs[cur].strip(), "```", ""]
            lines += [f"### Пара `{p['pair_id']}`", "", "```text", cands[p["cand_id"]].strip(), "```", ""]
        path = out / f"{name}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        paths.append(path)
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    manifest = {k: v for k, v in manifest.items() if not k.startswith(prefix + "_")}
    manifest.update({f"{prefix}_{i:02d}": [p["pair_id"] for p in b] for i, b in enumerate(batches, 1)})
    mpath.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return paths


def check(assessor_dir: Path, batches: Path = BLIND / "batches", only: str | None = None) -> dict:
    """Полнота и корректность меток агента по каждой пачке."""
    manifest = json.loads((batches / "manifest.json").read_text(encoding="utf-8"))
    report = {}
    for name, ids in manifest.items():
        f = assessor_dir / f"{name}.jsonl"
        if only and not name.startswith(only):
            continue
        if not f.exists():
            report[name] = "нет файла"
            continue
        got, bad = {}, 0
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                lab = int(r["label"])
                if lab not in (0, 1, 2, 3) or r["pair_id"] not in ids:
                    raise ValueError
                got[r["pair_id"]] = lab
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                bad += 1
        missing = len(set(ids) - set(got))
        report[name] = "ok" if not missing and not bad else f"нет меток: {missing}, ошибочных строк: {bad}"
    return report


def import_labels(
    assessor: str, assessor_dir: Path, data: Path = DATA, batches: Path = BLIND / "batches"
) -> dict:
    manifest = json.loads((batches / "manifest.json").read_text(encoding="utf-8"))
    valid = {pid for ids in manifest.values() for pid in ids}
    out_path = data / "judgments_llm.jsonl"
    rows = [r for r in load_jsonl(out_path) if r["model"] != assessor]  # переимпорт заменяет метки
    added = 0
    for f in sorted(assessor_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                lab = int(r["label"])
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if r.get("pair_id") in valid and lab in (0, 1, 2, 3):
                rows.append(
                    {
                        "pair_id": r["pair_id"],
                        "model": assessor,
                        "label": lab,
                        "rationale": str(r.get("rationale", ""))[:500],
                        "rubric": RUBRIC_VERSION,
                    }
                )
                valid.discard(r["pair_id"])  # дубли внутри асессора игнорируются
                added += 1
    out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return {"assessor": assessor, "imported": added, "not_labeled": len(valid)}
