from __future__ import annotations

import math
import random

from surgiflow.agents.plan import Plan
from surgiflow.agents.plan_cost import PlanCost
from surgiflow.sim.generator import generate

SA_STREAM = 8          # seed*1000 + 8: SA's own moves (scenarios use +7, generator +1..+3)
ACCEPT_AT_START = 0.8  # about 80% of uphill moves accepted at the first temperature

## the starting temperature
def initial_temperature(plan, cost_fn, rng, tries=30):
    """T0 so that an average uphill move is accepted with ACCEPT_AT_START."""
    base = cost_fn(plan)
    ups = []
    for _ in range(tries):
        cand = plan.neighbour(rng)
        if cand is not None:
            delta = cost_fn(cand) - base
            if delta > 0:
                ups.append(delta)
    if not ups:
        return 1.0
    return -(sum(ups) / len(ups)) / math.log(ACCEPT_AT_START)

##annealing loop
def anneal(plan, cost_fn, rng, iters=1000, t_end_frac=0.01):
    """Returns (best plan, its cost). Never worse than the starting plan."""
    cur, cur_c = plan, cost_fn(plan)
    best, best_c = cur, cur_c
    t = initial_temperature(plan, cost_fn, rng)
    alpha = t_end_frac ** (1 / iters)        # T reaches t_end_frac * T0 at the end
    for _ in range(iters):
        cand = cur.neighbour(rng)
        if cand is not None:
            c = cost_fn(cand)
            if c <= cur_c or rng.random() < math.exp((cur_c - c) / t):
                cur, cur_c = cand, c
                if c < best_c:
                    best, best_c = cand, c
        t *= alpha
    return best, best_c

##harness hook 
def sa_before_run(sim, cfg, seed, iters=1000, k=8):
    """Setup.before_run hook (D14): plan the day with SA, then apply the plan."""
    electives = generate(cfg, seed).electives          # planned fields only are used
    start = Plan.from_electives(electives, cfg)
    cost = PlanCost(electives, cfg, seed, sim.policy, sim.allocate, k=k)
    best, _ = anneal(start, cost, random.Random(seed * 1000 + SA_STREAM), iters=iters)
    sim.apply_plan(best.starts())