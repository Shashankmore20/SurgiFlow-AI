"""Where simulated days come from: Emmanuel's generator (2.6).

Every run gets FRESH patients and a fresh Network. The simulator writes into
both (Surgery.start_time/arrival/hospital, hospital queues, rooms and beds), so
reusing either leaks one run into the next. Reusing a Network took seed 1 from
cost 1261 to 47,916, because rooms still busy at minute 1440 were never freed.
"""
from __future__ import annotations

from surgiflow.sim.generator import generate, load_instance


def load_day(sim, cfg, seed):
    """Generate the day for `seed`, load it into `sim`, and return the patients
    the simulator will actually work on (load_instance's deep copy)."""
    loaded = load_instance(sim, generate(cfg, seed))
    return list(loaded.electives) + list(loaded.emergencies)
