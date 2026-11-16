"""Tests for the evaluation harness (2.9)."""
from pathlib import Path

from surgiflow.evaluation.days import load_day
from surgiflow.evaluation.harness import compare, evaluate, run_day, summarize
from surgiflow.evaluation.methods import METHODS, Method, Setup
from surgiflow.sim.core import Network, Simulator, nearest_capable_policy

BASE = Path(__file__).resolve().parent.parent / "configs" / "base.json"
FIFO, URGENCY = METHODS["fifo+nearest"], METHODS["urgency+nearest"]
COMPONENTS = ("wait", "delay", "overtime", "disruption", "imbalance", "transfers", "unserved")


def test_same_seed_same_result():
    assert run_day(FIFO, BASE, 3) == run_day(FIFO, BASE, 3)


def test_different_seeds_give_different_days():
    assert run_day(FIFO, BASE, 1)["total"] != run_day(FIFO, BASE, 2)["total"]


def test_results_do_not_depend_on_what_ran_before():
    # nothing (patients, network, policy state) leaks from one run into the next
    alone = evaluate([URGENCY], [0, 1], BASE)
    after_fifo = [r for r in evaluate([FIFO, URGENCY], [0, 1], BASE) if r["method"] == URGENCY.name]
    assert alone == after_fifo


def test_every_method_faces_the_same_patients():
    # operated + unserved + cancelled is fixed by the day, not by the method
    rows = evaluate(list(METHODS.values()), [0, 1, 2], BASE)
    for seed in (0, 1, 2):
        counts = {r["patients"] + r["cancelled"] for r in rows if r["seed"] == seed}
        assert len(counts) == 1


def test_parallel_matches_serial():
    m = list(METHODS.values())
    assert evaluate(m, [0, 1], BASE, workers=1) == evaluate(m, [0, 1], BASE, workers=2)


def build_lazy(cfg):
    return Setup(lambda hospital, clock: None, nearest_capable_policy)


def test_doing_nothing_loses_every_day():
    rows = evaluate([FIFO, Method("lazy", build_lazy)], [0, 1, 2], BASE)
    (c,) = compare(rows, "fifo+nearest")
    assert c["losses"] == 3 and c["mean_diff"] > 0


def test_load_day_returns_the_objects_the_simulator_used():
    import json
    cfg = json.loads(BASE.read_text())
    sim = Simulator(Network.from_config(BASE))
    patients = load_day(sim, cfg, 1)
    sim.run(until=cfg["horizon_min"])
    started = {r["surgery"] for r in sim.log}
    assert all(p.start_time is not None for p in patients if p.id in started)


def _row(method, seed, total):
    return {"method": method, "seed": seed, "total": total, "per_patient": total / 10,
            **{k: 0 for k in COMPONENTS}}


def test_summarize_and_compare_math():
    rows = ([_row("A", s, t) for s, t in [(0, 100), (1, 120), (2, 80)]] +
            [_row("B", s, t) for s, t in [(0, 90), (1, 130), (2, 80)]])
    a = next(s for s in summarize(rows) if s["method"] == "A")
    assert a["mean"] == 100 and a["days"] == 3 and round(a["std"]) == 20
    (c,) = compare(rows, "A")
    assert (c["wins"], c["losses"], c["ties"]) == (1, 1, 1)
    assert abs(c["mean_diff"]) < 1e-9
