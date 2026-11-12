"""Shared interfaces (task 1.5): the contracts every module codes against.

Pipeline:
    generator (2.6)  config + seed  ->  Instance          all randomness lives here
    simulator (2.x)  Instance + policies  ->  log         deterministic, no random numbers
    objective (1.6)  log + config  ->  (cost, components)

Rules:
  * Policies may read `expected_duration`, never `duration` (the true, hidden one).
  * Policies read the network/hospitals but never modify them.
  * Emergency `arrival` = call time, so its wait includes travel to the hospital.
  * Elective `arrival` = `planned_start` (it becomes available at its booked time).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from surgiflow.sim.core import Hospital, Network, Surgery


@dataclass
class Instance:
    """One simulated day, fully determined by (config, seed).

    The generator builds it; the simulator only reads it. Running every method
    on the same Instance is what makes comparisons fair.
    """
    seed: int
    config: dict
    electives: List[Surgery] = field(default_factory=list)   # hospital, planned_room/start set
    emergencies: List[Surgery] = field(default_factory=list) # zone, arrival (call time) set


class Generator(Protocol):
    """2.6: same config + seed must always give an identical Instance."""
    def __call__(self, config: dict, seed: int) -> Instance: ...


class SchedulingPolicy(Protocol):
    """Called when a room is free and someone is waiting at `hospital`.

    Return one of hospital.waiting to start now, or None to keep the room free.
    Examples: FIFO (core.fifo_policy), priority-first (2.7), SA/GA (3.x), RL (4.x).
    """
    def __call__(self, hospital: Hospital, clock: float) -> Optional[Surgery]: ...


class AllocationPolicy(Protocol):
    """Called when an emergency call comes in. Return the hospital id to send it to.

    Must return a hospital whose capabilities include patient.procedure.
    Examples: nearest capable hospital, capacity-aware heuristic (2.8), RL (4.x).
    """
    def __call__(self, patient: Surgery, network: Network, clock: float) -> int: ...


# Transfer hook (2.11) will be added here once transfers are designed.

# Fields in every simulator log record. The objective (1.6) relies on these.
LOG_FIELDS = (
    "surgery", "hospital", "room", "kind", "urgency", "procedure",
    "arrival", "start", "end", "planned_start", "transfers",
)
