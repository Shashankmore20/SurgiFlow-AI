"""Objective function: turns a simulation log into one cost number (lower is better).

Every method (baselines, SA/GA, RL) is scored with this same function, so the
comparison between them is fair. Each component is also returned separately,
so the report can show *why* one method beats another.

Expected record format (one dict per surgery in the log):
    hospital       int    hospital id
    room           int    room id within that hospital
    kind           str    "emergency" or "elective"
    urgency        int    1/2/3 for emergencies, None for electives
    arrival        float  emergencies: minute the call came in (wait includes travel)
    start, end     float  surgery start and end minute
    planned_start  float  original booked start (electives; None = no plan)
    transfers      int    times this patient was moved between hospitals
"""
from __future__ import annotations

from collections import defaultdict
from statistics import pstdev


def objective_components(records, config):
    regular = config["regular_hours_min"]
    max_wait = {u["level"]: u["max_wait_min"]
                for u in config["emergencies"]["urgency_levels"]}
    obj = config["objective"]

    wait = delay = disruption = 0.0
    transfers = 0
    room_last_end = {}
    busy = defaultdict(float)

    for r in records:
        if r["kind"] == "emergency":
            waited = r["start"] - r["arrival"]
            wait += obj["urgency_wait_multiplier"][str(r["urgency"])] * waited
            delay += max(0.0, waited - max_wait[r["urgency"]])
        elif r.get("planned_start") is not None:
            disruption += abs(r["start"] - r["planned_start"])
        transfers += r.get("transfers", 0)

        key = (r["hospital"], r["room"])
        room_last_end[key] = max(room_last_end.get(key, 0.0), r["end"])
        busy[r["hospital"]] += r["end"] - r["start"]

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
    }


def objective(records, config):
    # Weighted sum of the components. Returns (total_cost, components).
    parts = objective_components(records, config)
    w = config["objective"]["weights"]
    total = sum(w[name] * value for name, value in parts.items())
    return total, parts
