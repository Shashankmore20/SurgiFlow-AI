from .durations import sample_actual_duration

DEFAULT_STAY_MIN = 480   # used when base.json has no icu_stay_min for a procedure


def sample_bed_need(proc_cfg, rng):
    """Does this patient need a recovery/ICU bed afterwards, and for how long?

    Decided up front with the seeded generator (like durations), so every
    method faces the same patients. Returns (needs_bed, stay_minutes).
    """
    if rng.random() >= proc_cfg.get("icu_prob", 0.0):
        return False, 0
    mean = proc_cfg.get("icu_stay_min", DEFAULT_STAY_MIN)
    return True, sample_actual_duration(mean, rng, sigma=0.3)