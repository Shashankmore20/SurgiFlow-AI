"""Baseline policies (tasks 2.7 and 2.8). They are rules, not learning methods:
SA, GA and RL are compared against them."""
from __future__ import annotations

from typing import Optional

from surgiflow.sim.core import Hospital, Network, Surgery

ELECTIVE_RANK = 99   # electives have urgency None; rank them after every emergency


def urgency_first_policy(hospital: Hospital, clock: float) -> Optional[Surgery]:
    """Operate on the most urgent waiting patient (1 critical ... 3 semi-urgent).

    Ties go to whoever reached the hospital first, then to the lower id so the
    answer is always the same for the same input. Electives come after all
    emergencies. Never returns None while someone is waiting. Reads only
    urgency, arrival and id (never actual_duration) and does not modify
    hospital.waiting.
    """
    if not hospital.waiting:
        return None
    return min(
        hospital.waiting,
        key=lambda s: (s.urgency if s.urgency is not None else ELECTIVE_RANK,
                       s.arrival, s.id),
    )

def _estimated_start(hospital: Hospital, arrive: float, clock: float) -> float:
    """Estimate the minute a patient arriving at `arrive` would start surgery here.

    Uses only what a dispatcher can see now: planned durations (never
    actual_duration), who is in each room, who is waiting and who is inbound.
    Everyone already waiting or inbound is assumed to go first, each taking the
    earliest free room (greedy list scheduling). Does not modify the hospital.
    """
    # when each room is expected to free up; an overrunning surgery counts as "free now"
    free = [max(clock, room.current.start_time + room.current.duration)
            if room.current is not None else clock
            for room in hospital.rooms]
    for s in hospital.waiting + hospital.inbound:
        i = free.index(min(free))        # earliest free room takes the next patient ahead
        free[i] += s.duration
    return max(arrive, min(free))


def capacity_aware_policy(patient: Surgery, network: Network, clock: float) -> int:
    """Send the emergency where its surgery is expected to start soonest.

    For every hospital that can do the procedure, estimate call-to-surgery time
    (travel + expected queue wait) and pick the smallest. Ties go to the nearer
    hospital, then the lower id. Raises ValueError if no hospital is capable.
    """
    options = [h for h in network.hospitals if patient.procedure in h.capabilities]
    if not options:
        raise ValueError(f"no hospital can handle '{patient.procedure}'")

    def key(h):
        travel = network.travel_time(patient.zone, h.id)
        wait = _estimated_start(h, clock + travel, clock) - clock
        return (wait, travel, h.id)

    return min(options, key=key).id