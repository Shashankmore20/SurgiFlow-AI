"""Evaluation harness (2.9): run methods on many seeded days and compare them.

Every method faces the IDENTICAL days (same seeds -> same patients), so we can
compare them day by day, not just on averages. Standard library only, so it
runs in CI without extra installs.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import subprocess
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

from surgiflow.evaluation.days import load_day
from surgiflow.evaluation.objective import objective
from surgiflow.sim.core import Network, Simulator

COMPONENTS = ("wait", "delay", "overtime", "disruption", "imbalance", "transfers", "unserved")


def load_config(path):
    return json.loads(Path(path).read_text())


def run_day(method, config_path, seed):
    """One method on one day: fresh Network, fresh patients, fresh Setup."""
    cfg = load_config(config_path)
    setup = method.build(cfg)
    sim = Simulator(Network.from_config(config_path), policy=setup.policy, allocate=setup.allocate)
    load_day(sim, cfg, seed)
    if setup.before_run is not None:
        setup.before_run(sim, cfg, seed)
    sim.run(until=cfg["horizon_min"])
    total, parts = objective(sim.log, cfg, sim.unserved())
    return {
        "method": method.name, "seed": seed, "total": total,
        **{k: parts.get(k, 0) for k in COMPONENTS},
        "patients": parts["patients"],
        "per_patient": total / parts["patients"] if parts["patients"] else 0.0,
        "cancelled": len(sim.cancellations),
    }


def _run_one(args):
    return run_day(*args)


def evaluate(methods, seeds, config_path, workers=1):
    """Run every method on every seed. workers > 1 runs days in parallel."""
    jobs = [(m, config_path, s) for m in methods for s in seeds]
    if workers <= 1:
        rows = [_run_one(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_run_one, jobs, chunksize=max(1, len(jobs) // (workers * 4))))
    return sorted(rows, key=lambda r: (r["method"], r["seed"]))


def summarize(rows):
    """Per method: mean cost, spread across days, 95% confidence interval,
    per-patient cost and the mean of each component."""
    out = []
    for name in sorted({r["method"] for r in rows}):
        mine = [r for r in rows if r["method"] == name]
        totals = [r["total"] for r in mine]
        sd = statistics.stdev(totals) if len(totals) > 1 else 0.0
        out.append({
            "method": name, "days": len(mine),
            "mean": statistics.fmean(totals), "std": sd,
            "ci95": 1.96 * sd / math.sqrt(len(totals)),
            "per_patient": statistics.fmean(r["per_patient"] for r in mine),
            **{k: statistics.fmean(r[k] for r in mine) for k in COMPONENTS},
        })
    return out


def compare(rows, reference):
    """Each method vs the reference on the SAME days: wins (lower cost), losses,
    ties, and the average paired difference (negative = better than reference)."""
    ref = {r["seed"]: r["total"] for r in rows if r["method"] == reference}
    if not ref:
        raise ValueError(f"reference method '{reference}' has no results")
    out = []
    for name in sorted({r["method"] for r in rows} - {reference}):
        diffs = [r["total"] - ref[r["seed"]] for r in rows
                 if r["method"] == name and r["seed"] in ref]
        out.append({
            "method": name, "vs": reference, "days": len(diffs),
            "wins": sum(d < -1e-9 for d in diffs), "losses": sum(d > 1e-9 for d in diffs),
            "ties": sum(abs(d) <= 1e-9 for d in diffs),
            "mean_diff": statistics.fmean(diffs) if diffs else 0.0,
        })
    return out


def format_summary(summary, comparison=()):
    lines = [f"{'method':<20}{'days':>5}{'mean cost':>11}{'±95%':>8}{'/patient':>10}"
             f"{'wait':>8}{'delay':>8}{'overtime':>10}{'disrupt':>9}{'unserved':>10}"]
    for s in summary:
        lines.append(f"{s['method']:<20}{s['days']:>5}{s['mean']:>11.1f}{s['ci95']:>8.1f}"
                     f"{s['per_patient']:>10.2f}{s['wait']:>8.0f}{s['delay']:>8.0f}"
                     f"{s['overtime']:>10.0f}{s['disruption']:>9.0f}{s['unserved']:>10.2f}")
    for c in comparison:
        lines.append(f"\n{c['method']} vs {c['vs']}: better on {c['wins']}/{c['days']} days, "
                     f"worse on {c['losses']}, tied {c['ties']}; "
                     f"average difference {c['mean_diff']:+.1f}")
    return "\n".join(lines)


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


def save(rows, summary, comparison, out_dir, meta):
    """Write days.csv, summary.csv, comparison.csv and meta.json into a new
    timestamped folder, so earlier results are never overwritten."""
    folder = Path(out_dir) / datetime.now().strftime("eval_%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in (("days", rows), ("summary", summary), ("comparison", comparison)):
        if data:
            with open(folder / f"{name}.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)
    (folder / "meta.json").write_text(json.dumps({**meta, "commit": _git_commit()}, indent=2))
    return folder
