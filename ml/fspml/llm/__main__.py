"""python -m fspml.llm ping — проверка доступа к моделям AI Studio одним коротким запросом на модель."""

from __future__ import annotations

import os
import sys

from .client import LLMClient, load_dotenv


def ping() -> int:
    load_dotenv()
    client = LLMClient()
    client.check_ready()
    models = sorted(
        (
            set(os.environ.get("LLM_PANEL", "").split(","))
            | {os.environ.get(k, "") for k in ("LLM_MODEL_EXTRACT", "LLM_MODEL_GENERATOR", "LLM_MODEL_JUDGE")}
        )
        - {""}
    )
    failed = 0
    for m in models:
        try:
            r = client.chat(
                m,
                [{"role": "user", "content": "Ответь одним словом: столица России?"}],
                max_tokens=200,
                use_cache=False,
            )
            print(
                f"OK    {m:24s} {r.text.strip()[:40]!r}  ({r.input_tokens}+{r.output_tokens} ток., {r.cost_rub:.3f} ₽)"
            )
        except Exception as e:
            failed += 1
            print(f"FAIL  {m:24s} {str(e)[:160]}")
    print(f"Потрачено: {client.spent_rub:.3f} ₽")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:] != ["ping"]:
        sys.exit(__doc__)
    sys.exit(ping())
