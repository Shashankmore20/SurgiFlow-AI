"""Objective function: turns a simulation log into one cost number (lower is better).

Every method (baselines, SA/GA, RL) is scored with this same function, so the
comparison between them is fair. Each component is also returned separately,
so the report can show *why* one method beats another.

Expected record format (one dict per surgery in the log):
    hospital       int    hospital id
    room           int    room id within that hospital
    kind           str    "emergency" or "elective"
    urgency        int    1/2/3 for emergencies, None for electives
    call_time      float  emergencies: minute the call came in (falls back to arrival)
    start, end     float  surgery start and end minute
    room_release   float  when the room actually freed (later than end if bed-blocked)
    planned_start  float  original booked start (electives; None = no plan)
    transfers      int    times this patient was moved between hospitals
"""
from __future__ import annotations

from collections import defaultdict
from statistics import pstdev


def objective_components(records, config, unserved=()):
    """`records` = sim.log, `unserved` = sim.unserved() (patients never operated on)."""
    regular = config["regular_hours_min"]
    horizon = config.get("horizon_min", 1440)
    max_wait = {u["level"]: u["max_wait_min"]
                for u in config["emergencies"]["urgency_levels"]}
    obj = config["objective"]

    wait = delay = disruption = 0.0
    transfers = 0
    room_last_end = {}
    busy = defaultdict(float)

    for r in records:
        if r["kind"] == "emergency":
            call = r.get("call_time")
            call = r["arrival"] if call is None else call
            waited = r["start"] - call   # includes ambulance travel
            wait += obj["urgency_wait_multiplier"][str(r["urgency"])] * waited
            delay += max(0.0, waited - max_wait[r["urgency"]])
        elif r.get("planned_start") is not None:
            disruption += abs(r["start"] - r["planned_start"])
        transfers += r.get("transfers", 0)

        # Overtime = the regular day running late (D10): only surgeries that
        # STARTED in regular hours count. Night emergencies are on-call work.
        if r["start"] < regular:
            key = (r["hospital"], r["room"])
            freed = r.get("room_release") or r["end"]
            room_last_end[key] = max(room_last_end.get(key, 0.0), freed)
        busy[r["hospital"]] += r["end"] - r["start"]

    # Patients never operated on (D10). Emergencies keep accumulating wait and
    # delay until the end of the horizon; electives count as disrupted until then.
    # Both also get a flat per-patient penalty, so "just don't operate" never pays.
    for s in unserved:
        if s.emergency:
            call = s.call_time if s.call_time is not None else s.arrival
            waited = horizon - call
            wait += obj["urgency_wait_multiplier"][str(s.urgency)] * waited
            delay += max(0.0, waited - max_wait[s.urgency])
        elif s.planned_start is not None:
            disruption += max(0.0, horizon - s.planned_start)

    overtime = sum(max(0.0, end - regular) for end in room_last_end.values())

    utilization = [busy[h["id"]] / (h["n_or"] * regular) for h in config["hospitals"]]
    imbalance = pstdev(utilization) if len(utilization) > 1 else 0.0

    return {
        "wait": wait,               # urgency-weighted emergency wait (min)
        "delay": delay,             # minutes past each emergency's max wait
        "overtime": overtime,       # room-minutes past regular hours
        "disruption": disruption,   # minutes electives moved from their plan
        "imbalance": imbalance,     # std dev of hospital utilization (0-1 scale)
        "transfers": transfers,     # number of inter-hospital transfers
        "unserved": len(unserved),  # patients who never got surgery
        "patients": len(records) + len(unserved),  # for per-patient averages; not weighted
    }


def objective(records, config, unserved=()):
    """Weighted sum of the components. Returns (total_cost, components).

    `unserved` = sim.unserved(). Only components listed in
    config["objective"]["weights"] are added up; "patients" is reported
    but not weighted.
    """
    parts = objective_components(records, config, unserved)
    w = config["objective"]["weights"]
    total = sum(weight * parts[name] for name, weight in w.items())
    return total, parts
