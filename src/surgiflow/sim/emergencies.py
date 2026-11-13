from .core import Surgery
from .durations import sample_actual_duration
from .beds import sample_bed_need

MINUTES_PER_DAY = 1440

def generate_emergencies(cfg, rng):
    """Random emergencies for one horizon, from the base.json settings.

    Returns a list of (call_time, zone_index, Surgery), sorted by call time.
    Calls arrive as a random (Poisson) process at arrivals_per_day.
    """
    em = cfg["emergencies"]
    rate = em["arrivals_per_day"] / MINUTES_PER_DAY      # calls per minute
    levels = em["urgency_levels"]
    weights = [lv["prob"] for lv in levels]
    procedures = list(cfg["procedures"])
    n_zones = len(cfg["zones"])

    out, t, i = [], 0.0, 0
    while True:
        t += rng.expovariate(rate)
        if t >= cfg["horizon_min"]:
            break
        lv = rng.choices(levels, weights=weights)[0]
        proc = rng.choice(procedures)                     # equally likely for now
        planned = cfg["procedures"][proc]["mean_duration_min"]
        needs_bed, bed_stay = sample_bed_need(cfg["procedures"][proc], rng)
        s = Surgery(
            id=f"E{i}",
            duration=planned,
            # config level 1 = most urgent, but priority is "higher = more urgent"
            priority=len(levels) + 1 - lv["level"],
            urgency=lv["level"],          # 1 = critical (what the objective uses)
            emergency=True,
            actual_duration=sample_actual_duration(planned, rng),
            procedure=proc,
            max_wait=lv["max_wait_min"],
            needs_bed=needs_bed,
            bed_stay=bed_stay,
        )
        s.call_time, s.zone = int(t), rng.randrange(n_zones)
        out.append((s.call_time, s.zone, s))
        i += 1
    return out

def schedule_emergencies(sim, cfg, rng):
    """Generate emergencies and load them into the simulator."""
    for call_time, zone, s in generate_emergencies(cfg, rng):
        sim.add_emergency(s, call_time, zone)
