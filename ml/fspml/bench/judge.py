"""LLM-асессор: разметка пар «вакансия — кандидат» по рубрике ансамблем моделей.

Каждая модель размечает пары независимо (temperature=0, слепо к системам). Итоговая метка —
округлённое среднее по моделям. Перед использованием асессор сверяется с экспертами
(`fspml.bench.stats`): без приемлемого согласия его метки в оценку не идут.
"""

from __future__ import annotations

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..llm.client import LLMClient, LLMConfig, parse_json_object, price_rub
from .build import DATA, load_jsonl
from .rubric import RUBRIC_VERSION, SYSTEM_PROMPT, user_prompt

# Три разных семейства моделей — ошибки асессоров меньше коррелируют.
# qwen3-235b-a22b-fp8 недоступна в каталоге (403), поэтому её нет в ансамбле.
DEFAULT_JUDGES = ["deepseek-v4.1-flash", "yandexgpt-5.1", "gpt-oss-120b"]


CHARS_PER_TOKEN = 3.2  # грубая оценка для русского текста — только для прогноза стоимости


def _texts(data: Path) -> tuple[dict, dict, list[dict]]:
    needs = {r["need_id"]: r["text"] for r in load_jsonl(data / "needs.jsonl")}
    cands = {r["cand_id"]: r["text"] for r in load_jsonl(data / "candidates.jsonl")}
    pairs = load_jsonl(data / "pairs.jsonl")
    return needs, cands, pairs


def _subset(pairs: list[dict], limit: int | None) -> list[dict]:
    """Пробный прогон: фиксированная случайная выборка пар по всем потребностям (seed 0)."""
    if not limit or limit >= len(pairs):
        return pairs
    return random.Random(0).sample(pairs, limit)


def estimate(models: list[str], data: Path = DATA, limit: int | None = None) -> dict:
    """Прогноз токенов и стоимости без обращения к API."""
    needs, cands, pairs = _texts(data)
    pairs = _subset(pairs, limit)
    prices = LLMConfig.from_env().prices
    inp = (
        sum(len(SYSTEM_PROMPT) + len(user_prompt(needs[p["need_id"]], cands[p["cand_id"]])) for p in pairs)
        / CHARS_PER_TOKEN
    )
    out = 90 * len(pairs)
    per_model = {m: round(price_rub(prices, m, int(inp), out), 1) for m in models}
    return {
        "pairs": len(pairs),
        "input_tokens_per_model": int(inp),
        "output_tokens_per_model": out,
        "cost_rub": per_model,
        "total_rub": round(sum(per_model.values()), 1),
    }


def judge(
    models: list[str],
    data: Path = DATA,
    *,
    limit: int | None = None,
    workers: int = 8,
    client: LLMClient | None = None,
) -> dict:
    needs, cands, pairs = _texts(data)
    pairs = _subset(pairs, limit)
    client = client or LLMClient()
    out_path = data / "judgments_llm.jsonl"
    done = {(r["pair_id"], r["model"]) for r in load_jsonl(out_path) if r.get("rubric") == RUBRIC_VERSION}
    todo = [(p, m) for m in models for p in pairs if (p["pair_id"], m) not in done]
    print(f"К разметке: {len(todo)} (уже есть {len(done)})", file=sys.stderr)

    def one(p: dict, model: str) -> dict:
        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(needs[p["need_id"]], cands[p["cand_id"]])},
        ]
        comp = client.chat(model, msgs, temperature=0.0, max_tokens=400)
        try:
            obj = parse_json_object(comp.text)
            label = int(obj["label"])
            if label not in (0, 1, 2, 3):
                raise ValueError(label)
            rationale = str(obj.get("rationale", ""))[:500]
        except (ValueError, KeyError, TypeError) as e:
            return {
                "pair_id": p["pair_id"],
                "model": model,
                "label": None,
                "error": f"{e}: {comp.text[:200]}",
                "rubric": RUBRIC_VERSION,
            }
        return {
            "pair_id": p["pair_id"],
            "model": model,
            "label": label,
            "rationale": rationale,
            "rubric": RUBRIC_VERSION,
        }

    n_ok = n_err = 0
    with out_path.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(workers) as pool:
        futs = [pool.submit(one, p, m) for p, m in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            if row["label"] is None:
                n_err += 1
                continue  # ошибочный разбор не пишем — пара будет переразмечена при следующем запуске
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            n_ok += 1
            if i % 100 == 0:
                print(f"  {i}/{len(todo)} · потрачено {client.spent_rub:.1f} ₽", file=sys.stderr)
    return {
        "labeled": n_ok,
        "parse_errors": n_err,
        "api_calls": client.calls,
        "cache_hits": client.cache_hits,
        "spent_rub": round(client.spent_rub, 2),
    }


def aggregate(rows: list[dict], models: list[str] | None = None) -> dict[str, int]:
    """Итоговая метка пары: округлённое (половина — вверх) среднее по моделям ансамбля."""
    by_pair: dict[str, list[int]] = {}
    for r in rows:
        if r.get("label") is None or (models and r["model"] not in models):
            continue
        by_pair.setdefault(r["pair_id"], []).append(int(r["label"]))
    return {pid: int(sum(v) / len(v) + 0.5) for pid, v in by_pair.items()}
