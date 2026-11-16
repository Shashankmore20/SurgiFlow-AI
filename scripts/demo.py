"""Animated replay of one simulated day.

    python scripts/demo.py                                  # interactive window
    python scripts/demo.py --seed 3 --method urgency+nearest
    python scripts/demo.py --save results/demo.gif

Controls: space = play/pause, right/left = faster/slower, home = restart,
drag the slider to jump to any time. Methods and days come from the same
place as the evaluation harness, so the demo always shows what was measured.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from surgiflow.evaluation.days import load_day
from surgiflow.evaluation.harness import load_config
from surgiflow.evaluation.methods import METHODS
from surgiflow.evaluation.objective import objective
from surgiflow.sim.core import Network, Simulator
from surgiflow.viz.timeline import Timeline

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/base.json"


def run(cfg, seed, method_name):
    setup = METHODS[method_name].build(cfg)
    sim = Simulator(Network.from_config(CONFIG), policy=setup.policy, allocate=setup.allocate)
    patients = load_day(sim, cfg, seed)
    if setup.before_run is not None:
        setup.before_run(sim, cfg, seed)
    sim.run(until=cfg["horizon_min"])
    return sim, patients


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--method", choices=sorted(METHODS), default="fifo+nearest")
    ap.add_argument("--save", help="export instead of showing, e.g. results/demo.gif")
    ap.add_argument("--snapshot", type=int, help="save a PNG at this minute (with --save path)")
    args = ap.parse_args()

    cfg = load_config(CONFIG)
    sim, patients = run(cfg, args.seed, args.method)
    cost = objective(sim.log, cfg, sim.unserved())

    if args.save:
        import matplotlib
        matplotlib.use("Agg")
    from surgiflow.viz.viewer import ReplayViewer

    title = f"SurgiFlow  |  seed {args.seed}  |  {args.method}"
    viewer = ReplayViewer(Timeline(sim, patients, cfg), title=title, cost=cost)
    if args.save and args.snapshot is not None:
        viewer.snapshot(args.save, args.snapshot)
    elif args.save:
        viewer.save(args.save)
    else:
        viewer.show()


if __name__ == "__main__":
    main()
