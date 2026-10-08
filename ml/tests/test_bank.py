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
    """Ядро и модули каждой специализации измеримы: на каждый навык — не меньше 4 семейств
    (покрытие требует 2 задания на навык, ещё 2 — запас на повтор и вывод семейств из ротации)."""
    cat = get_catalog()
    per_skill = {s: sum(f.skill == s for f in FAMILIES) for s in {f.skill for f in FAMILIES}}
    for spec in cat.specializations.values():
        thin = {s: per_skill.get(s, 0) for s in spec.skills if per_skill.get(s, 0) < 4}
        assert not thin, f"{spec.id}: мало семейств для навыков {thin}"
        assert abs(sum(spec.core.values()) - 1) < 1e-9, f"{spec.id}: доли ядра не дают 1"


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


# Языки, где ответ задания вычисляет Python-модель семантики: код — полная программа, её запускает
# настоящий компилятор/интерпретатор. Без тулчейна тест пропускается локально; в CI тулчейны ставятся.
CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net{ver}</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>disable</ImplicitUsings>
    <NoWarn>CS0162;CS0219;CS8321</NoWarn>
  </PropertyGroup>
</Project>
"""


def _dotnet_major() -> str:
    out = subprocess.run(["dotnet", "--version"], capture_output=True, text=True, timeout=60).stdout
    return ".".join(out.strip().split(".")[:1]) + ".0"


def _runner(lang: str, workdir) -> list[str] | None:
    """Готовит рабочий каталог и возвращает команду запуска; None — тулчейна нет."""
    match lang:
        case "php":
            return ["php", str(workdir / "main.php")] if shutil.which("php") else None
        case "java":
            ok = (
                shutil.which("java")
                and subprocess.run(["java", "-version"], capture_output=True).returncode == 0
            )
            return ["java", str(workdir / "Main.java")] if ok else None
        case "go":
            if not shutil.which("go"):
                return None
            (workdir / "go.mod").write_text("module item\n\ngo 1.22\n")
            return ["go", "run", "."]
        case "csharp":
            if not shutil.which("dotnet"):
                return None
            (workdir / "item.csproj").write_text(CSPROJ.format(ver=_dotnet_major()))
            return ["dotnet", "run", "--nologo"]
    return None


SOURCE_FILE = {"php": "main.php", "java": "Main.java", "go": "main.go", "csharp": "Program.cs"}
RUNTIME_SEEDS = {"php": 15, "java": 5, "go": 5, "csharp": 3}


@pytest.mark.parametrize("lang", sorted(SOURCE_FILE))
def test_lang_families_match_runtime(lang, tmp_path):
    """Python-модель семантики Java, Go, C# и PHP сверяется с настоящими рантаймами."""
    cmd = _runner(lang, tmp_path)
    if cmd is None:
        pytest.skip(f"нет тулчейна для {lang}")
    fams = [f for f in FAMILIES if f.generate(0).explanation == lang]
    assert len(fams) >= 4, f"{lang}: мало исполняемых семейств"
    mismatches = []
    for fam in fams:
        for seed in range(RUNTIME_SEEDS[lang]):
            inst = fam.generate(seed)
            (tmp_path / SOURCE_FILE[lang]).write_text(inst.code)
            out = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, timeout=180)
            got = " ".join(out.stdout.split("\n")).strip()
            if out.returncode != 0 or not inst.check(got):
                mismatches.append((fam.id, seed, got or out.stderr[-500:], inst.answer))
    assert not mismatches, mismatches[:5]
