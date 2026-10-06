"""python -m fspml.bench {build|estimate|judge|label|import|eval}

build     — популяция, прогоны систем, пул пар для разметки (ml/bench/data)
estimate  — прогноз стоимости LLM-разметки без обращения к API
judge     — разметка пула LLM-асессорами (нужны YC_* и LLM_ENABLED=1 в .env)
label     — страница экспертной разметки (ml/bench/label/label.html)
import    — импорт JSON с результатами экспертов
add-system NAME — прогон новой версии механики и новые пары для доразметки
eval      — метрики систем и согласие асессоров → docs/bench-results.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .judge import DEFAULT_JUDGES


def main() -> None:
    p = argparse.ArgumentParser(
        prog="python -m fspml.bench",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--candidates", type=int, default=1000)
    b.add_argument("--needs", type=int, default=30, help="число синтетических потребностей")
    b.add_argument("--no-neural", action="store_true", help="без FRIDA/Qwen3/bge-reranker")
    for name in ("estimate", "judge"):
        s = sub.add_parser(name)
        s.add_argument("--models", default=",".join(DEFAULT_JUDGES))
        s.add_argument("--limit", type=int, default=None, help="случайная выборка из N пар (пробный прогон)")
        if name == "judge":
            s.add_argument("--workers", type=int, default=8)
    lab = sub.add_parser("label")
    lab.add_argument("-n", type=int, default=160)
    imp = sub.add_parser("import")
    imp.add_argument("files", nargs="+", type=Path)
    bl = sub.add_parser("blind")
    bl.add_argument("--size", type=int, default=100)
    bc = sub.add_parser("blind-check")
    bc.add_argument("dir", type=Path)
    bi = sub.add_parser("blind-import")
    bi.add_argument("name")
    bi.add_argument("dir", type=Path)
    ad = sub.add_parser("add-system")
    ad.add_argument("names", nargs="+")
    ds = sub.add_parser("distill")
    ds.add_argument("--teacher", default="claude-opus-5-5")
    ev = sub.add_parser("eval")
    ev.add_argument("--models", default=None, help="подмножество моделей ансамбля")
    a = p.parse_args()

    if a.cmd == "build":
        from .build import build

        build(a.candidates, a.needs, neural=not a.no_neural)
    elif a.cmd == "estimate":
        from .judge import estimate

        print(json.dumps(estimate(a.models.split(","), limit=a.limit), ensure_ascii=False, indent=2))
    elif a.cmd == "judge":
        from .judge import judge

        print(
            json.dumps(
                judge(a.models.split(","), limit=a.limit, workers=a.workers), ensure_ascii=False, indent=2
            )
        )
    elif a.cmd == "label":
        from .human import export_html

        print(export_html(a.n))
    elif a.cmd == "import":
        from .human import import_results

        print(import_results(a.files))
    elif a.cmd == "blind":
        from .blind import export_batches

        for path in export_batches(a.size):
            print(path)
    elif a.cmd == "blind-check":
        from .blind import check

        for name, status in check(a.dir).items():
            print(f"{name}: {status}")
    elif a.cmd == "blind-import":
        from .blind import import_labels

        print(import_labels(a.name, a.dir))
    elif a.cmd == "add-system":
        from .build import add_systems

        print(add_systems(a.names))
    elif a.cmd == "distill":
        from .distill import run as distill

        print(json.dumps(distill(a.teacher), ensure_ascii=False, indent=2))
    elif a.cmd == "eval":
        from .evaluate import REPORT_MD, run

        run(models=a.models.split(",") if a.models else None)
        print(REPORT_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
