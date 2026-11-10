import random

from surgiflow.sim.beds import sample_bed_need
from surgiflow.sim.core import Hospital, Network, Simulator, Surgery
from surgiflow.sim.emergencies import generate_emergencies


def net(n_rooms, n_beds):
    return Network([Hospital(0, n_rooms, recovery_beds=n_beds)], ["Z0"], [[0]])


def rows(sim):
    return {r["surgery"]: r for r in sim.log}


def test_no_bed_needed_changes_nothing():
    sim = Simulator(net(1, 0))
    sim.add_surgery(Surgery("A", 60), 0)
    sim.add_surgery(Surgery("B", 30), 0)
    sim.run()
    r = rows(sim)
    assert r["A"]["room_release"] == 60 and r["A"]["blocked_min"] == 0
    assert r["B"]["start"] == 60


def test_free_bed_releases_room_immediately():
    sim = Simulator(net(1, 1))
    sim.add_surgery(Surgery("A", 60, needs_bed=True, bed_stay=120), 0)
    sim.add_surgery(Surgery("B", 30), 0)
    sim.run()
    r = rows(sim)
    assert r["A"]["room_release"] == 60 and r["A"]["blocked_min"] == 0
    assert r["B"]["start"] == 60
    assert sim.network.hospitals[0].beds_in_use == 0   # bed freed at 180


def test_no_free_bed_blocks_the_room():
    sim = Simulator(net(2, 1))
    sim.add_surgery(Surgery("A", 60, needs_bed=True, bed_stay=200), 0)  # bed until 260
    sim.add_surgery(Surgery("B", 80, needs_bed=True, bed_stay=50), 0)   # finds no bed at 80
    sim.add_surgery(Surgery("C", 30), 0)
    sim.add_surgery(Surgery("D", 30), 0)
    sim.run()
    r = rows(sim)
    assert r["C"]["start"] == 60                       # A's room is free at 60
    assert r["D"]["start"] == 90                       # B's room is stuck, so D waits for C's room
    assert r["D"]["room"] == r["C"]["room"] == r["A"]["room"]
    assert r["B"]["room_release"] == 260               # got the bed when A's stay ended
    assert r["B"]["blocked_min"] == 180
    assert r["A"]["blocked_min"] == 0
    assert sim.network.hospitals[0].beds_in_use == 0


def test_blocked_patients_get_beds_in_order():
    sim = Simulator(net(3, 1))
    sim.add_surgery(Surgery("A", 10, needs_bed=True, bed_stay=100), 0)  # bed until 110
    sim.add_surgery(Surgery("B", 20, needs_bed=True, bed_stay=10), 0)   # blocked from 20
    sim.add_surgery(Surgery("C", 30, needs_bed=True, bed_stay=10), 0)   # blocked from 30
    sim.run()
    r = rows(sim)
    assert r["B"]["room_release"] == 110 and r["C"]["room_release"] == 120


def test_bed_need_sampler():
    rng = random.Random(0)
    assert sample_bed_need({"icu_prob": 0.0}, rng) == (False, 0)
    needs, stay = sample_bed_need({"icu_prob": 1.0}, rng)
    assert needs and stay >= 1
    assert sample_bed_need({}, rng) == (False, 0)      # no icu_prob given
    a = [sample_bed_need({"icu_prob": 0.5}, random.Random(3)) for _ in range(5)]
    b = [sample_bed_need({"icu_prob": 0.5}, random.Random(3)) for _ in range(5)]
    assert a == b


def test_emergency_generator_uses_icu_prob():
    cfg = {
        "horizon_min": 1440, "zones": ["Z0"],
        "procedures": {"general": {"mean_duration_min": 90, "icu_prob": 0.0},
                       "cardiac": {"mean_duration_min": 180, "icu_prob": 1.0}},
        "emergencies": {"arrivals_per_day": 12, "urgency_levels": [
            {"level": 1, "label": "critical", "max_wait_min": 60, "prob": 1.0}]},
    }
    for seed in range(20):
        for _, _, s in generate_emergencies(cfg, random.Random(seed)):
            assert s.needs_bed == (s.procedure == "cardiac")
            assert (s.bed_stay > 0) == s.needs_bed