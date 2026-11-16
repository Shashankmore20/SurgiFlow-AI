"""Compare methods across many seeded days.

    python scripts/evaluate.py                         # all methods, 50 days
    python scripts/evaluate.py --seeds 200 --workers 8
    python scripts/evaluate.py --methods fifo+nearest urgency+nearest

Results go to results/eval_<timestamp>/ (days.csv, summary.csv,
comparison.csv, meta.json). Methods are registered in
src/surgiflow/evaluation/methods.py.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from surgiflow.evaluation.harness import compare, evaluate, format_summary, save, summarize
from surgiflow.evaluation.methods import METHODS

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", nargs="+", choices=sorted(METHODS), default=sorted(METHODS))
    ap.add_argument("--seeds", type=int, default=50, help="number of days (seeds 0..N-1)")
    ap.add_argument("--config", default=str(ROOT / "configs/base.json"))
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--reference", default="fifo+nearest")
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()

    methods = [METHODS[m] for m in args.methods]
    seeds = list(range(args.seeds))
    rows = evaluate(methods, seeds, args.config, workers=args.workers)
    summary = summarize(rows)
    comparison = compare(rows, args.reference) if args.reference in args.methods else []

    print(format_summary(summary, comparison))
    folder = save(rows, summary, comparison, args.out, meta={
        "config": args.config, "seeds": [seeds[0], seeds[-1]], "methods": args.methods,
        "reference": args.reference})
    print(f"\nSaved to {folder}")


if __name__ == "__main__":
    main()
