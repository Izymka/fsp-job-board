"""Граф смежности технологий: структура, канонические имена, допустимые веса."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import fspml
import pytest
import yaml
from fspml.nlp.skills import get_dictionary

GRAPH_PATH = Path(fspml.__file__).parent / "data" / "skill_graph.yaml"
ALLOWED_WEIGHTS = {0.8, 0.6, 0.4, 0.25}


@pytest.fixture(scope="module")
def graph() -> dict:
    with GRAPH_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def edges(graph: dict) -> list[dict]:
    return graph["edges"]


def test_header(graph: dict, edges: list[dict]):
    assert graph["version"] == 1
    assert isinstance(edges, list) and edges
    for e in edges:
        assert set(e) == {"from", "to", "w", "why"}, e


def test_names_are_canonical(edges: list[dict]):
    techs = get_dictionary().techs
    unknown = sorted({e[k] for e in edges for k in ("from", "to")} - set(techs))
    assert not unknown, f"нет в skills.yaml: {unknown}"


def test_no_self_loops(edges: list[dict]):
    loops = [e["from"] for e in edges if e["from"] == e["to"]]
    assert not loops, f"петли: {loops}"


def test_no_duplicate_pairs(edges: list[dict]):
    pairs = Counter((e["from"], e["to"]) for e in edges)
    dups = [p for p, n in pairs.items() if n > 1]
    assert not dups, f"дубли: {dups}"


def test_weights_on_scale(edges: list[dict]):
    bad = [(e["from"], e["to"], e["w"]) for e in edges if e["w"] not in ALLOWED_WEIGHTS]
    assert not bad, f"недопустимые веса: {bad}"


def test_why_not_empty(edges: list[dict]):
    empty = [(e["from"], e["to"]) for e in edges if not str(e["why"] or "").strip()]
    assert not empty, f"пустое why: {empty}"
