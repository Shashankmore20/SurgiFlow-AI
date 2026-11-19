from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, replace
from typing import Dict, List, Tuple

from surgiflow.evaluation.objective import objective
from surgiflow.sim.beds import sample_bed_need
from surgiflow.sim.core import Network, Simulator, Surgery
from surgiflow.sim.durations import sample_actual_duration
from surgiflow.sim.emergencies import generate_emergencies

SCENARIO_STREAM = 7      # seed*1000 + 7; generator streams are +1, +2, +3 (D11)
ROOM_CHANGE_MIN = 30     # stability: changing a case's room counts like moving it 30 min


@dataclass
class Scenario:
    electives: Dict[str, Tuple[int, bool, int]]   # id -> (actual_duration, needs_bed, bed_stay)
    emergencies: List[Surgery]                     # call_time and zone already set


def make_scenarios(electives, config, seed, k=8):
    """K what-if days for these electives. Reads only planned fields."""
    rng = random.Random(seed * 1000 + SCENARIO_STREAM)
    dur_sigma = config.get("duration_sigma", 0.25)
    bed_sigma = config.get("bed_stay_sigma", 0.3)
    out = []
    for _ in range(k):
        el = {}
        for s in electives:
            needs_bed, stay = sample_bed_need(config["procedures"][s.procedure], rng, sigma=bed_sigma)
            el[s.id] = (sample_actual_duration(s.duration, rng, sigma=dur_sigma), needs_bed, stay)
        emergencies = [s for _, _, s in generate_emergencies(config, rng)]
        out.append(Scenario(el, emergencies))
    return out


def run_scenario(plan, electives, scenario, config, policy, allocate):
    """Objective total of one plan on one what-if day. Works on copies, so
    neither the electives nor the scenario are changed."""
    sim = Simulator(Network.from_dict(config), policy=policy, allocate=allocate)
    starts = plan.starts()
    for s in electives:
        h, r, t = starts[s.id]
        dur, needs_bed, stay = scenario.electives[s.id]
        sim.add_surgery(replace(s, planned_room=r, planned_start=t, actual_duration=dur,
                                needs_bed=needs_bed, bed_stay=stay),
                        arrival_time=t, hospital=h)
    for e in scenario.emergencies:
        sim.add_emergency(replace(e), e.call_time, e.zone)
    sim.run(until=config["horizon_min"])
    total, _ = objective(sim.log, config, sim.unserved())
    return total


def stability(plan, ref):
    """Minutes each case moved from `ref`, plus ROOM_CHANGE_MIN per room change."""
    a, b = plan.starts(), ref.starts()
    return sum(abs(a[i][2] - b[i][2]) + (ROOM_CHANGE_MIN if a[i][1] != b[i][1] else 0)
               for i in a)


class PlanCost:
    """cost(plan) = mean objective over the scenarios + lam * stability(plan, ref).

    Build one per day; SA/GA call it thousands of times.
    """

    def __init__(self, electives, config, seed, policy, allocate, k=8, ref=None, lam=0.0):
        self.electives = list(electives)
        self.config = config
        self.policy, self.allocate = policy, allocate
        self.scenarios = make_scenarios(self.electives, config, seed, k)
        self.ref, self.lam = ref, lam

    def expected(self, plan):
        return statistics.fmean(run_scenario(plan, self.electives, sc, self.config,
                                             self.policy, self.allocate)
                                for sc in self.scenarios)

    def __call__(self, plan):
        cost = self.expected(plan)
        if self.lam and self.ref is not None:
            cost += self.lam * stability(plan, self.ref)
        return cost
