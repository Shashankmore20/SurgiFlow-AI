import json
import math
import random
from pathlib import Path

import pytest

from surgiflow.agents.baselines import capacity_aware_policy, urgency_first_policy
from surgiflow.agents.plan import Plan
from surgiflow.agents.plan_cost import PlanCost
from surgiflow.agents.sa import anneal, initial_temperature
from surgiflow.evaluation.harness import evaluate
from surgiflow.evaluation.methods import METHODS, Method, build_sa_fast
from surgiflow.sim.core import Network, Simulator
from surgiflow.sim.generator import generate, load_instance

PATH = Path(__file__).resolve().parents[1] / "configs" / "base.json"
CFG = json.loads(PATH.read_text())
POLICIES = (urgency_first_policy, capacity_aware_policy)
TOY = Plan(rooms=((("a", "b", "c"),),), duration={"a": 60, "b": 90, "c": 30}, limit=600)


def c_starts_at(plan):
    """Toy cost: the minute case c starts. Best possible plan puts c first (cost 0)."""
    return plan.starts()["c"][2]


# ---- anneal -----------------------------------------------------------------
def test_anneal_finds_the_toy_optimum():
    best, cost = anneal(TOY, c_starts_at, random.Random(0), iters=200)
    assert cost == 0 and best.starts()["c"] == (0, 0, 0)


def test_anneal_never_returns_worse_than_the_start():
    electives = generate(CFG, 1).electives
    start = Plan.from_electives(electives, CFG)
    cost = PlanCost(electives, CFG, 1, *POLICIES, k=2)
    best, best_c = anneal(start, cost, random.Random(0), iters=60)
    assert best_c <= cost(start) and best.is_valid()


def test_anneal_is_reproducible():
    electives = generate(CFG, 2).electives
    start = Plan.from_electives(electives, CFG)
    cost = PlanCost(electives, CFG, 2, *POLICIES, k=2)
    a, _ = anneal(start, cost, random.Random(5), iters=60)
    b, _ = anneal(start, cost, random.Random(5), iters=60)
    assert a.starts() == b.starts()


def test_initial_temperature_accepts_80_percent_of_an_average_uphill_move():
    t0 = initial_temperature(TOY, lambda p: 0 if p is TOY else 10, random.Random(0))
    assert abs(math.exp(-10 / t0) - 0.8) < 1e-9


def test_initial_temperature_when_nothing_is_uphill():
    assert initial_temperature(TOY, lambda p: 0, random.Random(0)) == 1.0


# ---- Simulator.apply_plan ---------------------------------------------------
def run(seed, plan_fn=None):
    sim = Simulator(Network.from_config(PATH), *POLICIES)
    loaded = load_instance(sim, generate(CFG, seed))
    if plan_fn is not None:
        sim.apply_plan(plan_fn(loaded.electives).starts())
    sim.run(until=CFG["horizon_min"])
    return sim


def test_applying_the_default_plan_changes_nothing():
    plain = run(3)
    same = run(3, lambda el: Plan.from_electives(el, CFG))
    assert plain.log == same.log and plain.cancellations == same.cancellations


def test_electives_arrive_at_the_applied_plan():
    def reordered(el):
        plan, rng = Plan.from_electives(el, CFG), random.Random(1)
        for _ in range(50):
            plan = plan.neighbour(rng) or plan
        reordered.starts = plan.starts()
        return plan
    sim = run(4, reordered)
    electives = [r for r in sim.log if not r["emergency"]]
    assert electives
    for r in electives:
        _, room, start = reordered.starts[r["surgery"]]
        assert r["planned_start"] == start and r["arrival"] == start and r["start"] >= start


def test_apply_plan_rejects_bad_use():
    sim = Simulator(Network.from_config(PATH), *POLICIES)
    loaded = load_instance(sim, generate(CFG, 5))
    starts = Plan.from_electives(loaded.electives, CFG).starts()
    some_id = next(iter(starts))
    h, r, t = starts[some_id]
    with pytest.raises(ValueError):
        sim.apply_plan({**starts, some_id: ((h + 1) % 3, r, t)})   # other hospital
    sim.run(until=10)
    with pytest.raises(ValueError):
        sim.apply_plan(starts)                                    # day already running


# ---- harness ----------------------------------------------------------------
def test_sa_is_registered_and_runs_in_the_harness():
    assert "sa+urgency+capacity" in METHODS
    rows = evaluate([METHODS["urgency+capacity"], Method("sa-fast", build_sa_fast)], [0, 1], PATH)
    assert {r["method"] for r in rows} == {"urgency+capacity", "sa-fast"}
    assert all(r["total"] > 0 for r in rows)