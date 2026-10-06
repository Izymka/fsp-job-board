"""Бенчмарк подбора: LLM-клиент (без сети), статистика, агрегация меток, сборка пула."""

from __future__ import annotations

import json

import httpx
import pytest
from fspml.bench import stats as st
from fspml.bench.judge import aggregate
from fspml.llm.client import LLMClient, LLMConfig, LLMDisabled, parse_json_object


def _cfg(tmp_path, **kw) -> LLMConfig:
    base = dict(
        enabled=True,
        folder_id="b1gtest",
        api_key="test-key",
        cache_path=tmp_path / "c.sqlite",
        budget_rub=10.0,
    )
    base.update(kw)
    return LLMConfig(**base)


def _reply(content: str, inp: int = 1000, out: int = 100) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": inp, "completion_tokens": out},
    }


def test_client_headers_uri_cache_and_cost(tmp_path):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=_reply('{"label": 2}'))

    c = LLMClient(_cfg(tmp_path), transport=httpx.MockTransport(handler))
    msgs = [{"role": "user", "content": "x"}]
    r1 = c.chat("qwen3-235b-a22b-fp8", msgs)
    r2 = c.chat("qwen3-235b-a22b-fp8", msgs)
    assert len(seen) == 1, "второй вызов должен прийти из кэша"
    req = seen[0]
    assert req.headers["x-data-logging-enabled"] == "false"
    assert req.headers["authorization"] == "Bearer test-key"
    assert json.loads(req.content)["model"] == "gpt://b1gtest/qwen3-235b-a22b-fp8"
    assert r1.cost_rub == pytest.approx((1000 * 0.5 + 100 * 0.5) / 1000)
    assert r2.cached and r2.cost_rub == 0
    assert c.spent_rub == pytest.approx(r1.cost_rub)


def test_client_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("fspml.llm.client.time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, text="rate") if calls["n"] < 3 else httpx.Response(200, json=_reply("ok"))

    c = LLMClient(_cfg(tmp_path), transport=httpx.MockTransport(handler))
    assert c.chat("gpt-oss-20b", [{"role": "user", "content": "y"}]).text == "ok"
    assert calls["n"] == 3


def test_client_budget_and_disabled(tmp_path):
    c = LLMClient(
        _cfg(tmp_path, budget_rub=0.0),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_reply("ok"))),
    )
    with pytest.raises(RuntimeError, match="бюджет"):
        c.chat("gpt-oss-20b", [{"role": "user", "content": "z"}])
    off = LLMClient(_cfg(tmp_path, enabled=False))
    with pytest.raises(LLMDisabled):
        off.chat("gpt-oss-20b", [{"role": "user", "content": "w"}])


def test_parse_json_object_variants():
    assert parse_json_object('```json\n{"label": 3, "rationale": "a}b"}\n```')["label"] == 3
    assert parse_json_object('Оценка: {"rationale": "ok", "label": 1} — всё')["label"] == 1
    with pytest.raises(ValueError):
        parse_json_object("нет json")


def test_aggregate_rounds_half_up():
    rows = [
        {"pair_id": "a", "model": "m1", "label": 1},
        {"pair_id": "a", "model": "m2", "label": 2},
        {"pair_id": "b", "model": "m1", "label": 3},
        {"pair_id": "b", "model": "m2", "label": None},
    ]
    assert aggregate(rows) == {"a": 2, "b": 3}
    assert aggregate(rows, ["m1"]) == {"a": 1, "b": 3}


def test_ndcg_condensed_ignores_unjudged():
    q = {"a": 3, "b": 0, "c": 2}
    assert st.ndcg_condensed(["a", "x", "c", "b"], q) == pytest.approx(1.0)
    assert st.ndcg_condensed(["b", "c", "a"], q) < 1.0
    assert st.ndcg_condensed(["a"], {"a": 0}) is None
    assert st.judged_at_k(["a", "x"], q) == 0.5


def test_agreement_statistics():
    a = [0, 1, 2, 3, 3, 2, 1, 0]
    assert st.weighted_kappa(a, a) == pytest.approx(1.0)
    assert st.krippendorff_alpha_interval(
        {str(i): {"x": v, "y": v} for i, v in enumerate(a)}
    ) == pytest.approx(1.0)
    noisy = {str(i): {"x": v, "y": 3 - v} for i, v in enumerate(a)}
    assert st.krippendorff_alpha_interval(noisy) < 0
    assert st.kendall_tau([1, 2, 3], [1, 2, 3]) == 1.0


def test_randomization_test_detects_difference():
    assert st.randomization_test([1.0] * 20, [0.0] * 20) < 0.01
    assert st.randomization_test([0.5] * 10, [0.5] * 10) == 1.0


def test_build_pool_small(tmp_path):
    from fspml.bench.build import build, load_jsonl

    meta = build(n_candidates=200, n_synthetic=3, neural=False, out=tmp_path)
    pairs = load_jsonl(tmp_path / "pairs.jsonl")
    cands = {r["cand_id"]: r["text"] for r in load_jsonl(tmp_path / "candidates.jsonl")}
    assert meta["n_pairs"] == len(pairs) > 0
    assert len({p["pair_id"] for p in pairs}) == len(pairs), "пары не дублируются"
    assert {p["kind"] for p in pairs} == {"pooled", "random", "control"}
    # карточка обезличена и не содержит скрытой истины
    text = next(iter(cands.values()))
    assert text.startswith("Кандидат K-") and "theta" not in text and "накрут" not in text
