"""Панель LLM-респондентов: локальные модели Qwen3 разного размера решают экземпляры заданий.

Зачем. Параметры IRT заданий (сложность b, различающая сила a) назначены экспертно. Чтобы
измерить их до появления живых кандидатов, задания решает «популяция» из моделей разной силы:
0.6B … 8B, с рассуждением и без, с несколькими сэмплами. Разброс способностей этой популяции
даёт материал для MML-EM-калибровки (`fit.py`).

Модели исполняются локально через MLX (Apple Silicon): задания и ответы никуда не уходят.
Ответ модели проверяется тем же `ItemInstance.check`, что и ответ кандидата.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..assessment.bank import REGISTRY
from ..assessment.items import ItemInstance

CALIB_DIR = Path(__file__).resolve().parents[2] / "bench" / "calib"

MODELS = {
    "q06": "mlx-community/Qwen3-0.6B-4bit",
    "q17": "mlx-community/Qwen3-1.7B-4bit",
    "q4": "mlx-community/Qwen3-4B-4bit",
    "q8": "mlx-community/Qwen3-8B-4bit",
}


@dataclass(frozen=True)
class Respondent:
    model: str  # ключ MODELS
    think: bool
    temp: float
    sample: int  # номер сэмпла (seed)

    @property
    def id(self) -> str:
        return f"{self.model}{'-think' if self.think else ''}-t{self.temp:g}-s{self.sample}"


def panel(samples: int = 3, think_models: tuple[str, ...] = ("q06", "q17", "q4")) -> list[Respondent]:
    out = []
    for m in MODELS:
        for s in range(samples):
            out.append(Respondent(m, False, 0.7, s))
            if m in think_models and s == 0:  # рассуждение дорого: один сэмпл на модель
                out.append(Respondent(m, True, 0.6, s))
    return out


SYSTEM = (
    "Ты проходишь технический тест для IT-специалиста. Реши задание. "
    "В последней строке ответа обязательно напиши «Ответ: …» в указанном формате."
)

FORMAT_HINT = {
    "single": "Формат: «Ответ: N», где N — номер одного варианта.",
    "multi": "Формат: «Ответ: N1, N2, …» — номера всех верных вариантов через запятую.",
    "order": "Формат: «Ответ: N1, N2, …» — номера вариантов в правильном порядке через запятую.",
    "number": "Формат: «Ответ: число».",
    "text": "Формат: «Ответ: значение» (без пояснений).",
}


def render(inst: ItemInstance) -> str:
    parts = [inst.prompt.strip()]
    if inst.code:
        parts.append(f"```{inst.code_lang or ''}\n{inst.code.rstrip()}\n```")
    if inst.options:
        parts.append("\n".join(f"{i + 1}. {o}" for i, o in enumerate(inst.options)))
    parts.append(FORMAT_HINT[inst.kind])
    return "\n\n".join(parts)


ANSWER_RE = re.compile(r"Ответ\s*[:：]\s*(.+)", re.IGNORECASE)


def parse_answer(inst: ItemInstance, text: str):
    """Ответ модели → формат, который принимает ItemInstance.check. None — не разобрано."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    hits = ANSWER_RE.findall(text)
    if not hits:
        return None
    raw = hits[-1].strip().strip("*`«»\"' .")
    if inst.kind in ("single", "multi", "order"):
        nums = [int(n) - 1 for n in re.findall(r"\d+", raw)]
        if not nums:
            return None
        return nums[0] if inst.kind == "single" else nums
    if inst.kind == "number":
        m = re.search(r"-?\d+(?:[.,]\d+)?", raw.replace(" ", ""))
        return m.group(0) if m else None
    return raw


class Runner:
    def __init__(self, model_key: str) -> None:
        from mlx_lm import load

        self.model, self.tokenizer = load(MODELS[model_key])

    def ask(self, inst: ItemInstance, r: Respondent) -> str:
        import mlx.core as mx
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": render(inst)}]
        prompt = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False, enable_thinking=r.think
        )
        # детерминированный seed (встроенный hash() строк солится в каждом процессе)
        key = f"{r.id}|{inst.family_id}|{inst.prompt[:200]}".encode()
        mx.random.seed(int(hashlib.md5(key).hexdigest(), 16) % (2**31))
        return generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=1024 if r.think else 384,
            sampler=make_sampler(temp=r.temp, top_p=0.95),
            verbose=False,
        )


def instances(per_family: int = 2) -> list[tuple[str, int, ItemInstance]]:
    out = []
    for fid, fam in sorted(REGISTRY.items()):
        for k in range(per_family):
            seed = 10_000 + k
            out.append((fid, seed, fam.generate(seed)))
    return out


def run(
    per_family: int = 2, samples: int = 3, models: list[str] | None = None, out: Path | None = None
) -> dict:
    out = out or CALIB_DIR / "responses.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["respondent"], r["family"], r["seed"]))
    items = instances(per_family)
    resp = [r for r in panel(samples) if not models or r.model in models]
    stats = {"answered": 0, "unparsed": 0}
    with out.open("a", encoding="utf-8") as fh:
        for model_key in dict.fromkeys(r.model for r in resp):
            runner = Runner(model_key)
            todo = [
                (r, it)
                for r in resp
                if r.model == model_key
                for it in items
                if (r.id, it[0], it[1]) not in done
            ]
            t0 = time.time()
            for i, (r, (fid, seed, inst)) in enumerate(todo, 1):
                text = runner.ask(inst, r)
                ans = parse_answer(inst, text)
                ok = bool(ans is not None and inst.check(ans))
                stats["answered"] += 1
                stats["unparsed"] += ans is None
                fh.write(
                    json.dumps(
                        {
                            "respondent": r.id,
                            "model": r.model,
                            "think": r.think,
                            "family": fid,
                            "seed": seed,
                            "correct": ok,
                            "parsed": ans is not None,
                            "tail": text[-160:],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                fh.flush()
                if i % 50 == 0:
                    rate = (time.time() - t0) / i
                    print(f"  {model_key}: {i}/{len(todo)} · {rate:.1f} с/ответ", file=sys.stderr, flush=True)
            del runner
    return stats
