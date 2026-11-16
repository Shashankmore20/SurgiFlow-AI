"""The methods the harness can compare.

A method is a name plus a `build(cfg)` function that returns a fresh Setup
for ONE day. Fresh matters: SA keeps a plan and RL keeps a Q-table, and a
day must never inherit state from the previous one. (A trained RL agent is
loaded inside build(), read-only.)

Setup:
  policy      scheduling policy(hospital, clock) -> Surgery | None
  allocate    allocation policy(patient, network, clock) -> hospital id
  before_run  optional hook(sim, cfg, seed) after the day is loaded and before
              it runs, e.g. SA/GA replacing the elective plan (3.x)

To add a method (2.8, SA, GA, RL): write a top-level build function and add it
to METHODS. It must be top-level (no lambdas) so the parallel runner can send
it to other processes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from surgiflow.agents.baselines import urgency_first_policy
from surgiflow.sim.core import fifo_policy, nearest_capable_policy


@dataclass
class Setup:
    policy: Callable
    allocate: Callable
    before_run: Optional[Callable] = None


@dataclass(frozen=True)
class Method:
    name: str
    build: Callable


# ---- baselines (2.7 scheduling x 2.8 allocation) --------------------------
def build_fifo_nearest(cfg):
    return Setup(fifo_policy, nearest_capable_policy)


def build_urgency_nearest(cfg):
    return Setup(urgency_first_policy, nearest_capable_policy)


# 2.8 capacity-aware allocation: add e.g. build_urgency_capacity here.

METHODS = {m.name: m for m in [
    Method("fifo+nearest", build_fifo_nearest),
    Method("urgency+nearest", build_urgency_nearest),
]}
