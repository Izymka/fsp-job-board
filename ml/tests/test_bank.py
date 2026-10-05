"""Автопроверки банка заданий: корректность, разнообразие экземпляров, сверка JS-модели с Node.js."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from fspml.assessment.bank import REGISTRY
from fspml.catalog import get_catalog

FAMILIES = sorted(REGISTRY.values(), key=lambda f: f.id)
SEEDS = range(30)


def test_bank_covers_all_blueprint_skills():
    cat = get_catalog()
    skills = {f.skill for f in FAMILIES}
    for spec in cat.specializations.values():
        for lang in spec.stack_languages or (None,):
            bp = cat.blueprint(spec.id, [lang] if lang else None)
            missing = set(bp) - skills
            assert not missing, f"{spec.id}: нет семейств для навыков {missing}"


def test_every_skill_spans_levels():
    """Для адаптивности у каждого навыка должны быть семейства хотя бы трёх разных уровней."""
    by_skill: dict[str, set[int]] = {}
    for f in FAMILIES:
        by_skill.setdefault(f.skill, set()).add(f.level)
    thin = {s: lv for s, lv in by_skill.items() if len(lv) < 3}
    assert not thin, f"мало уровней сложности: {thin}"


@pytest.mark.parametrize("fam", FAMILIES, ids=lambda f: f.id)
def test_family_instances_are_valid(fam):
    for seed in SEEDS:
        inst = fam.generate(seed)
        assert inst.prompt.strip()
        assert inst.check(inst.answer), f"{fam.id} seed={seed}: правильный ответ не принимается"
        public = inst.public()
        assert "answer" not in public
        if inst.kind in ("single", "multi", "order"):
            assert inst.options and len(inst.options) == len(set(inst.options)), f"{fam.id}: дубли вариантов"
            assert len(inst.options) >= 2
        if inst.kind == "single":
            wrong = (inst.answer + 1) % len(inst.options)
            assert not inst.check(wrong)
        if inst.kind == "number":
            assert not inst.check(float(inst.answer) + inst.tolerance + 1)


@pytest.mark.parametrize("fam", FAMILIES, ids=lambda f: f.id)
def test_family_is_deterministic_by_seed(fam):
    a, b = fam.generate(12345), fam.generate(12345)
    assert a.prompt == b.prompt and a.code == b.code and a.answer == b.answer and a.options == b.options


@pytest.mark.parametrize("fam", FAMILIES, ids=lambda f: f.id)
def test_family_has_instance_diversity(fam):
    """Утечка одного экземпляра не должна раскрывать остальные: экземпляры различаются."""
    variants = set()
    for seed in range(60):
        inst = fam.generate(seed)
        variants.add((inst.prompt, inst.code, json.dumps(inst.options, ensure_ascii=False)))
    assert len(variants) >= 3, f"{fam.id}: всего {len(variants)} различных экземпляров"


def test_bank_answer_diversity_for_computed_items():
    """Для вычислимых семейств правильный ответ меняется от экземпляра к экземпляру (утёкший ключ бесполезен)."""
    weak = []
    for fam in FAMILIES:
        if fam.c > 0:  # задания с выбором: ответ — позиция варианта, она перемешивается
            continue
        answers = {json.dumps(fam.generate(s).answer, ensure_ascii=False, default=str) for s in range(60)}
        if len(answers) < 3:
            weak.append((fam.id, len(answers)))
    assert not weak, f"слабое разнообразие ответов: {weak}"


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js не установлен")
def test_js_families_match_node():
    """Python-модель семантики JS сверяется с настоящим Node.js."""
    mismatches = []
    for fam in FAMILIES:
        if fam.skill != "javascript":
            continue
        for seed in range(15):
            inst = fam.generate(seed)
            if inst.explanation != "js":
                continue
            out = subprocess.run([NODE, "-e", inst.code], capture_output=True, text=True, timeout=10)
            got = (
                "".join(out.stdout.split("\n"))
                if inst.normalize == "nospace"
                else " ".join(out.stdout.split("\n")).strip()
            )
            if not inst.check(got):
                mismatches.append((fam.id, seed, got, inst.answer))
    assert not mismatches, mismatches[:5]
