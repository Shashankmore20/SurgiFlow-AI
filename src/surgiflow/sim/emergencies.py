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
        mix = em.get("procedure_mix")
        if mix:
            names = list(mix)
            proc = rng.choices(names, weights=[mix[p] for p in names])[0]
        else:
            proc = rng.choice(procedures)                      # equally likely for now
        planned = cfg["procedures"][proc]["mean_duration_min"]
        needs_bed, bed_stay = sample_bed_need(cfg["procedures"][proc], rng, sigma=cfg.get("bed_stay_sigma", 0.3))
        s = Surgery(
            id=f"E{i}",
            duration=planned,
            emergency=True,
            urgency=lv["level"],
            actual_duration=sample_actual_duration(planned, rng, sigma=cfg.get("duration_sigma", 0.25)),
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
