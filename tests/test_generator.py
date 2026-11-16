"""Tests for the seeded instance generator (task 2.6)."""
import json
import random
from pathlib import Path

from surgiflow.sim.emergencies import generate_emergencies
from surgiflow.sim.generator import generate

CFG = json.loads((Path(__file__).parent.parent / "configs" / "base.json").read_text())


# ---------- Step 2: determinism and the emergency stream ----------

def test_same_seed_gives_identical_day():
    """The core promise: same config + seed, same Instance, every time."""
    assert generate(CFG, 1) == generate(CFG, 1)


def test_different_seeds_give_different_days():
    """Different seeds must actually produce different days."""
    assert generate(CFG, 1).emergencies != generate(CFG, 2).emergencies


def test_emergencies_come_from_their_own_stream():
    """Emergencies are exactly what generate_emergencies gives with the
    emergency stream (seed*1000 + 2), so electives/cancellations can't shift them."""
    expected = [s for _, _, s in generate_emergencies(CFG, random.Random(7 * 1000 + 2))]
    assert generate(CFG, 7).emergencies == expected


def test_instance_records_seed_and_config():
    inst = generate(CFG, 3)
    assert inst.seed == 3 and inst.config is CFG

# ---------- Step 3: electives (the hospital's default plan) ----------

SEEDS = range(1, 21)          # check rules on many days, not just one lucky one
CAPS = {h["id"]: h["capabilities"] for h in CFG["hospitals"]}
TARGET = CFG["electives"]["target_utilization"] * CFG["regular_hours_min"]   # 510
LONGEST = max(CFG["procedures"][p]["mean_duration_min"] for p in ("general", "cardiac"))


def rooms(inst):
    """{(hospital, room): [electives in booked order]}"""
    out = {}
    for s in inst.electives:
        out.setdefault((s.hospital, s.planned_room), []).append(s)
    return out


def test_electives_are_general_or_cardiac_and_hospital_can_do_them():
    """No trauma is booked ahead, and nobody is booked where the procedure isn't
    available (so Northside gets general only)."""
    for seed in SEEDS:
        for s in generate(CFG, seed).electives:
            assert s.procedure in ("general", "cardiac")
            assert s.procedure in CAPS[s.hospital]


def test_every_room_has_electives():
    """All 9 rooms (4 + 3 + 2) get a plan."""
    n_rooms = sum(h["n_or"] for h in CFG["hospitals"])
    for seed in SEEDS:
        assert len(rooms(generate(CFG, seed))) == n_rooms


def test_rooms_are_back_to_back_from_minute_zero():
    """First case at 0; each next case starts when the previous planned one ends;
    an elective arrives exactly at its planned start."""
    for seed in SEEDS:
        for cases in rooms(generate(CFG, seed)).values():
            t = 0
            for s in cases:
                assert s.planned_start == t and s.arrival == t
                t += s.duration


def test_room_totals_stop_near_target_and_inside_regular_hours():
    """'Closer to 510' rule: a room stops within half a longest case of 510
    (420..599 here), so the planned day never needs overtime."""
    for seed in SEEDS:
        for cases in rooms(generate(CFG, seed)).values():
            total = sum(s.duration for s in cases)
            assert TARGET - LONGEST / 2 <= total < TARGET + LONGEST / 2
            assert total < CFG["regular_hours_min"]


def test_average_utilization_is_about_85_percent():
    """Across many days the plan fills about 85% of regular hours."""
    totals = [sum(s.duration for s in cases)
              for seed in range(1, 101)
              for cases in rooms(generate(CFG, seed)).values()]
    avg = sum(totals) / len(totals) / CFG["regular_hours_min"]
    assert 0.80 <= avg <= 0.90


def test_elective_ids_unique_and_not_emergency_ids():
    """The simulator tracks cancellations by id, so ids must never repeat,
    and must not clash with emergencies (E0, E1, ...)."""
    for seed in SEEDS:
        inst = generate(CFG, seed)
        ids = [s.id for s in inst.electives + inst.emergencies]
        assert len(ids) == len(set(ids))
        assert not any(s.id.startswith("E") for s in inst.electives)


def test_electives_are_not_emergencies():
    for s in generate(CFG, 1).electives:
        assert s.emergency is False and s.urgency is None and s.kind == "elective"


def test_emergencies_unchanged_by_adding_electives():
    """Step 2's stream test, re-checked here on purpose: electives use their own
    stream, so the emergency day is exactly what it was before electives existed."""
    expected = [s for _, _, s in generate_emergencies(CFG, random.Random(1 * 1000 + 2))]
    assert generate(CFG, 1).emergencies == expected



    # ---------- Step 4: cancellations ----------

def with_cancel_prob(p):
    """A copy of the config with a different cancellation probability."""
    cfg = json.loads(json.dumps(CFG))                 # simple deep copy of plain JSON
    cfg.setdefault("electives", {})["cancellation_prob"] = p
    return cfg


def test_cancellations_are_real_electives_cancelled_before_they_start():
    """Every cancellation names an elective of that day, its minute is before the
    elective's planned start, and a case booked at minute 0 is never cancelled."""
    for seed in SEEDS:
        inst = generate(CFG, seed)
        start = {s.id: s.planned_start for s in inst.electives}
        for sid, when in inst.cancellations:
            assert sid in start
            assert 0 <= when < start[sid]
            assert start[sid] > 0


def test_each_elective_cancelled_at_most_once():
    for seed in SEEDS:
        ids = [sid for sid, _ in generate(CFG, seed).cancellations]
        assert len(ids) == len(set(ids))


def test_about_five_percent_of_electives_are_cancelled():
    """Over 200 days, the cancelled share is near 5%. Cases at minute 0 can't be
    cancelled, so the share among all electives sits a little under 5%."""
    n_el = n_cancel = 0
    for seed in range(1, 201):
        inst = generate(CFG, seed)
        n_el += len(inst.electives)
        n_cancel += len(inst.cancellations)
    assert 0.03 <= n_cancel / n_el <= 0.06


def test_changing_cancel_prob_changes_nothing_else():
    """Cancellations have their own stream: a different probability leaves the
    electives and emergencies of the day exactly as they were."""
    a, b = generate(with_cancel_prob(0.05), 4), generate(with_cancel_prob(0.5), 4)
    assert a.electives == b.electives
    assert a.emergencies == b.emergencies


def test_changing_cancel_prob_keeps_cancel_times():
    """Two draws per elective, always: anyone cancelled at 5% is still cancelled
    at 50%, at the same minute. Raising the probability only adds cancellations."""
    low = dict(generate(with_cancel_prob(0.05), 4).cancellations)
    high = dict(generate(with_cancel_prob(0.5), 4).cancellations)
    for sid, when in low.items():
        assert high[sid] == when


def test_zero_cancel_prob_means_no_cancellations():
    assert generate(with_cancel_prob(0.0), 1).cancellations == []


# ---------- Step 5: load_instance ----------

import copy

from surgiflow.agents.baselines import urgency_first_policy
from surgiflow.sim.core import Network, Simulator
from surgiflow.sim.generator import load_instance

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "base.json"


def run_day(inst, **policies):
    """One full run of a day. A fresh Network every time: the simulator also
    writes into hospitals (waiting lists, rooms), not just into patients."""
    sim = Simulator(Network.from_config(CONFIG_PATH), **policies)
    load_instance(sim, inst)
    sim.run(until=CFG["horizon_min"])
    return sim


def test_original_instance_is_never_changed():
    """Shashank's deepcopy point: after a full run the Instance is exactly as
    the generator made it (no start_time, arrival or hospital written on it)."""
    inst = generate(CFG, 1)
    before = copy.deepcopy(inst)
    run_day(inst)
    assert inst == before
    assert all(s.start_time is None for s in inst.electives + inst.emergencies)


def test_same_instance_twice_gives_identical_logs():
    """Run 2 does not inherit anything from run 1."""
    inst = generate(CFG, 1)
    assert run_day(inst).log == run_day(inst).log


def test_two_methods_on_one_instance_both_start_clean():
    """FIFO then urgency-first on the same Instance: the second run is identical
    to urgency-first on a freshly generated copy of the same day."""
    inst = generate(CFG, 2)
    run_day(inst)                                            # FIFO first
    after_fifo = run_day(inst, policy=urgency_first_policy).log
    fresh = run_day(generate(CFG, 2), policy=urgency_first_policy).log
    assert after_fifo == fresh


def test_cancelled_electives_are_never_operated_on():
    """Every generated cancellation reaches the simulator and is honoured."""
    for seed in SEEDS:
        inst = generate(CFG, seed)
        sim = run_day(inst)
        cancelled = {sid for sid, _ in inst.cancellations}
        operated = {r["surgery"] for r in sim.log}
        assert not cancelled & operated
        assert {c["surgery"] for c in sim.cancellations} == cancelled


def test_every_patient_is_accounted_for():
    """Each patient of the day is exactly one of: operated on, cancelled, unserved."""
    for seed in SEEDS:
        inst = generate(CFG, seed)
        sim = run_day(inst)
        operated = [r["surgery"] for r in sim.log]
        cancelled = [c["surgery"] for c in sim.cancellations]
        unserved = [s.id for s in sim.unserved()]
        everyone = [s.id for s in inst.electives + inst.emergencies]
        assert sorted(operated + cancelled + unserved) == sorted(everyone)


def test_electives_arrive_at_their_planned_start_in_the_run():
    """In the log, an elective's arrival is its booked minute (D9)."""
    sim = run_day(generate(CFG, 1))
    for r in sim.log:
        if not r["emergency"]:
            assert r["arrival"] == r["planned_start"]