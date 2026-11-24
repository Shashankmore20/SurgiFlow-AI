import json
import random
from dataclasses import replace
from pathlib import Path

from surgiflow.agents.baselines import capacity_aware_policy, urgency_first_policy
from surgiflow.agents.plan import Plan
from surgiflow.agents.plan_cost import PlanCost, make_scenarios, run_scenario, stability
from surgiflow.sim.core import Network
from surgiflow.sim.generator import generate

PATH = Path(__file__).resolve().parents[1] / "configs" / "base.json"
CFG = json.loads(PATH.read_text())
POLICIES = (urgency_first_policy, capacity_aware_policy)


def day(seed):
    electives = generate(CFG, seed).electives
    return electives, Plan.from_electives(electives, CFG)


def test_from_dict_matches_from_config():
    a, b = Network.from_config(PATH), Network.from_dict(CFG)
    assert [(h.id, len(h.rooms), h.recovery_beds, h.capabilities) for h in a.hospitals] == \
           [(h.id, len(h.rooms), h.recovery_beds, h.capabilities) for h in b.hospitals]
    assert a.travel_time_min == b.travel_time_min and a.transfer_time_min == b.transfer_time_min


def test_same_inputs_same_cost():
    electives, plan = day(1)
    a = PlanCost(electives, CFG, 1, *POLICIES, k=4)
    b = PlanCost(electives, CFG, 1, *POLICIES, k=4)
    assert a(plan) == b(plan) == a(plan)        # repeatable, and calling twice changes nothing
    assert a(plan) > 0


def test_planner_never_reads_the_real_days_hidden_values():
    electives, plan = day(2)
    honest = PlanCost(electives, CFG, 2, *POLICIES, k=4)(plan)
    tampered = [replace(s, actual_duration=999, needs_bed=True, bed_stay=5000) for s in electives]
    assert PlanCost(tampered, CFG, 2, *POLICIES, k=4)(plan) == honest


def test_scenarios_are_not_the_real_day():
    inst = generate(CFG, 3)
    real = [(e.call_time, e.zone, e.procedure) for e in inst.emergencies]
    for sc in make_scenarios(inst.electives, CFG, 3, k=4):
        assert [(e.call_time, e.zone, e.procedure) for e in sc.emergencies] != real


def test_scenarios_differ_from_each_other():
    electives, _ = day(4)
    scs = make_scenarios(electives, CFG, 4, k=3)
    assert len({tuple(sorted(sc.electives.items())) for sc in scs}) == 3


def test_cost_is_the_mean_over_scenarios():
    electives, plan = day(5)
    cost = PlanCost(electives, CFG, 5, *POLICIES, k=3)
    each = [run_scenario(plan, electives, sc, CFG, *POLICIES) for sc in cost.scenarios]
    assert abs(cost(plan) - sum(each) / 3) < 1e-9


def test_running_a_scenario_changes_nothing():
    electives, plan = day(6)
    sc = make_scenarios(electives, CFG, 6, k=1)[0]
    before = ([vars(s).copy() for s in electives], dict(sc.electives),
              [vars(e).copy() for e in sc.emergencies])
    run_scenario(plan, electives, sc, CFG, *POLICIES)
    after = ([vars(s).copy() for s in electives], dict(sc.electives),
             [vars(e).copy() for e in sc.emergencies])
    assert before == after


def test_cost_reacts_to_the_plan():
    electives, plan = day(1)                    # seed 1 has room to move cases
    cost = PlanCost(electives, CFG, 1, *POLICIES, k=4)
    rng = random.Random(0)
    others = [p for p in (plan.neighbour(rng) for _ in range(60)) if p is not None]
    assert any(cost(p) != cost(plan) for p in others)


def test_stability_by_hand():
    ref = Plan(rooms=((("a", "b"), ("c",)),), duration={"a": 60, "b": 90, "c": 30}, limit=600)
    assert stability(ref, ref) == 0
    swapped = Plan(rooms=((("b", "a"), ("c",)),), duration=ref.duration, limit=600)
    assert stability(swapped, ref) == 90 + 60                  # a: 0->90, b: 60->0
    moved = Plan(rooms=((("a",), ("c", "b")),), duration=ref.duration, limit=600)
    assert stability(moved, ref) == abs(30 - 60) + 30          # b: 60->30 and changed room


def test_lam_adds_the_stability_penalty():
    electives, plan = day(1)
    rng = random.Random(1)
    other = next(p for p in (plan.neighbour(rng) for _ in range(100)) if p is not None)
    base = PlanCost(electives, CFG, 1, *POLICIES, k=2)
    penalised = PlanCost(electives, CFG, 1, *POLICIES, k=2, ref=plan, lam=0.5)
    assert penalised(plan) == base(plan)                        # no change from ref: no penalty
    assert abs(penalised(other) - (base(other) + 0.5 * stability(other, plan))) < 1e-9
