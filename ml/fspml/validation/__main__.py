"""python -m fspml.validation [--out docs] [--quick]"""

from __future__ import annotations

import argparse
from pathlib import Path

from .report import run


def main() -> None:
    p = argparse.ArgumentParser(description="Воспроизводимая валидация механик тестирования и подбора")
    p.add_argument("--out", default="docs", type=Path)
    p.add_argument("--quick", action="store_true", help="уменьшенная популяция для быстрой проверки")
    args = p.parse_args()
    res = run(args.out, quick=args.quick)
    rel, m = res["reliability"], res["matching"]["systems"]["ours"]
    print(
        f"Готово за {res['elapsed_sec']} с → {args.out / 'validation.md'}\n"
        f"  грейд: точность {rel['accuracy_exact']:.1%}, ретест {rel['retest_agreement']:.1%} (взв. κ {rel['retest_kappa_weighted']:.2f})\n"
        f"  подбор: NDCG@10 {m['ndcg@10']:.3f}, P@10 {m['p@10']:.3f}"
    )


if __name__ == "__main__":
    main()
