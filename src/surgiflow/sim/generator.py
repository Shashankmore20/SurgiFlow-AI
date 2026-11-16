"""Seeded instance generator (task 2.6).

generate(config, seed) builds one simulated day as an Instance. All randomness
in the project happens here (D9); the simulator and policies are deterministic,
so every method can be run on exactly the same day.
"""
from __future__ import annotations

import copy
import random

from surgiflow.interfaces import Instance
from surgiflow.sim.beds import sample_bed_need
from surgiflow.sim.core import Surgery
from surgiflow.sim.durations import sample_actual_duration
from surgiflow.sim.emergencies import generate_emergencies

# Fallbacks until these keys are in base.json (Shashank's point 4, Zaiba's task).
DEFAULT_ELECTIVE_MIX = {"general": 0.7, "cardiac": 0.3}
DEFAULT_TARGET_UTILIZATION = 0.85
DEFAULT_CANCELLATION_PROB = 0.05

def _streams(seed):
    """One random generator per part of the day, so changing how one part is
    drawn never shifts the numbers another part gets."""
    return (random.Random(seed * 1000 + 1),   # electives
            random.Random(seed * 1000 + 2),   # emergencies
            random.Random(seed * 1000 + 3))   # cancellations


def _electives(config, rng):
    """The hospital's default plan: every room filled back to back from minute 0.

    A case is added only if it brings the room's planned total closer to the
    target (85% of regular hours = 510 min); otherwise the room is full. Each
    hospital only gets procedures it can do, so Northside gets general only.
    """
    el = config.get("electives", {})
    mix = el.get("procedure_mix", DEFAULT_ELECTIVE_MIX)
    target = el.get("target_utilization", DEFAULT_TARGET_UTILIZATION) * config["regular_hours_min"]

    out = []
    for h in config["hospitals"]:
        allowed = [p for p in mix if p in h["capabilities"]]
        if not allowed:
            continue
        weights = [mix[p] for p in allowed]
        for room in range(h["n_or"]):
            t, k = 0, 0
            while True:
                proc = rng.choices(allowed, weights=weights)[0]
                proc_cfg = config["procedures"][proc]
                planned = proc_cfg["mean_duration_min"]
                if abs(t + planned - target) >= abs(t - target):
                    break                        # this case would not get closer: room is full
                needs_bed, bed_stay = sample_bed_need(proc_cfg, rng)
                out.append(Surgery(
                    id=f"H{h['id']}-R{room}-{k}",
                    duration=planned,
                    actual_duration=sample_actual_duration(planned, rng),
                    procedure=proc,
                    hospital=h["id"],
                    planned_room=room,
                    planned_start=t,
                    arrival=t,                   # electives are available at their booked time (D9)
                    needs_bed=needs_bed,
                    bed_stay=bed_stay,
                ))
                t += planned
                k += 1
    return out


def _cancellations(config, electives, rng):
    """About 5% of electives are cancelled at a random minute before their start.

    Every elective uses exactly two draws (cancelled? and when?), even if it is
    not cancelled, so changing the probability never shifts anyone's cancel time.
    A case booked at minute 0 can't be cancelled before it starts, so it never is.
    Returns [(surgery id, cancel minute)].
    """
    p = config.get("electives", {}).get("cancellation_prob", DEFAULT_CANCELLATION_PROB)
    out = []
    for s in electives:
        cancelled = rng.random() < p
        when = int(rng.random() * s.planned_start)   # 0 <= when < planned_start
        if cancelled and s.planned_start > 0:
            out.append((s.id, when))
    return out

def generate(config: dict, seed: int) -> Instance:
    """Build one day from the config and seed. Same inputs give the same day."""
    rng_electives, rng_emergencies, rng_cancel = _streams(seed)

    electives = _electives(config, rng_electives)
    emergencies = [s for _, _, s in generate_emergencies(config, rng_emergencies)]
    cancellations = _cancellations(config, electives, rng_cancel)

    return Instance(seed=seed, config=config, electives=electives,
                    emergencies=emergencies, cancellations=cancellations)

def load_instance(sim, instance: Instance) -> Instance:
    """Put one day into a simulator, in a fixed order.

    The simulator writes into Surgery objects (arrival, hospital, start_time), so
    each run gets its own deep copy and the original Instance is never changed;
    the same day can then be run under many methods. Cancellations hold only ids,
    so they are matched to the copied surgeries by id. Load order is fixed
    (electives, emergencies, cancellations) because same-minute events are handled
    in the order they were added. Returns the copy that was loaded.
    """
    inst = copy.deepcopy(instance)
    for s in inst.electives:
        sim.add_surgery(s, arrival_time=s.planned_start, hospital=s.hospital)
    for s in inst.emergencies:
        sim.add_emergency(s, s.call_time, s.zone)
    by_id = {s.id: s for s in inst.electives}
    for sid, when in inst.cancellations:
        sim.cancel_surgery(by_id[sid], when)
    return inst