"""Baseline policies (tasks 2.7 and 2.8). They are rules, not learning methods:
SA, GA and RL are compared against them."""
from __future__ import annotations

from typing import Optional

from surgiflow.sim.core import Hospital, Surgery

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