"""Архетипы технологических стеков: структура, канонические имена, доли."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import fspml
import pytest
import yaml
from fspml.catalog import get_catalog
from fspml.nlp.skills import get_dictionary

ARCHETYPES_PATH = Path(fspml.__file__).parent / "data" / "stack_archetypes.yaml"
TIERS = {"core": (2, 4), "common": (3, 7), "optional": (2, 6)}


@pytest.fixture(scope="module")
def archetypes() -> list[dict]:
    with ARCHETYPES_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert data["version"] == 1
    assert isinstance(data["archetypes"], list) and data["archetypes"]
    return data["archetypes"]


def test_ids_unique(archetypes: list[dict]) -> None:
    dup = [k for k, n in Counter(a["id"] for a in archetypes).items() if n > 1]
    assert not dup, f"дубли id: {dup}"


def test_specs_from_catalog(archetypes: list[dict]) -> None:
    specs = set(get_catalog().specializations)
    used = {a["spec"] for a in archetypes}
    assert used <= specs, f"неизвестные spec: {used - specs}"
    assert used == specs, f"специализации без архетипов: {specs - used}"


def test_shares_sum_to_one(archetypes: list[dict]) -> None:
    totals: dict[str, float] = defaultdict(float)
    for a in archetypes:
        assert 0 < a["share"] <= 1, a["id"]
        totals[a["spec"]] += a["share"]
    for spec, total in totals.items():
        assert total == pytest.approx(1.0, abs=1e-6), f"{spec}: {total}"


def test_names_canonical(archetypes: list[dict]) -> None:
    techs = get_dictionary().techs
    bad = [(a["id"], name) for a in archetypes for tier in TIERS for name in a[tier] if name not in techs]
    assert not bad, f"неканонические имена: {bad}"


def test_tier_sizes(archetypes: list[dict]) -> None:
    for a in archetypes:
        for tier, (lo, hi) in TIERS.items():
            assert lo <= len(a[tier]) <= hi, f"{a['id']}.{tier}: {len(a[tier])}"


def test_no_duplicates_within_archetype(archetypes: list[dict]) -> None:
    for a in archetypes:
        names = [n for tier in TIERS for n in a[tier]]
        dup = [k for k, n in Counter(names).items() if n > 1]
        assert not dup, f"{a['id']}: дубли {dup}"
