"""python -m fspml.calib {run|fit}

run  — панель локальных LLM-респондентов решает экземпляры заданий (ml/bench/calib/responses.jsonl)
fit  — MML-EM-калибровка по ответам → data/calibrated_params.json, docs/calib-results.md
"""

from __future__ import annotations

import argparse
import json


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m fspml.calib", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--per-family", type=int, default=2)
    r.add_argument("--samples", type=int, default=3)
    r.add_argument("--models", default=None, help="подмножество: q06,q17,q4,q8")
    sub.add_parser("fit")
    a = p.parse_args()
    if a.cmd == "run":
        from .respondents import run

        print(run(a.per_family, a.samples, a.models.split(",") if a.models else None))
    else:
        from .fit import fit

        res = fit()
        print(json.dumps({k: v for k, v in res.items() if k != "families"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
