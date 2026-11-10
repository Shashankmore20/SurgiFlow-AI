import random

from surgiflow.sim.core import Network, Simulator, Surgery
from surgiflow.sim.durations import sample_actual_duration


def test_room_is_busy_for_actual_not_planned():
    sim = Simulator(Network.single(n_rooms=1))
    sim.add_surgery(Surgery("A", 60, actual_duration=90), 0)
    sim.add_surgery(Surgery("B", 30), 0)
    sim.run()
    r = {x["surgery"]: x for x in sim.log}
    assert r["A"]["end"] == 90 and r["A"]["planned"] == 60 and r["A"]["actual"] == 90
    assert r["B"]["start"] == 90   # waited for the overrun


def test_same_seed_same_durations():
    a = [sample_actual_duration(90, random.Random(7)) for _ in range(5)]
    b = [sample_actual_duration(90, random.Random(7)) for _ in range(5)]
    assert a == b


def test_different_seeds_differ():
    a = [sample_actual_duration(90, random.Random(1)) for _ in range(20)]
    b = [sample_actual_duration(90, random.Random(2)) for _ in range(20)]
    assert a != b


def test_average_matches_planned():
    rng = random.Random(0)
    xs = [sample_actual_duration(120, rng) for _ in range(20000)]
    assert abs(sum(xs) / len(xs) - 120) < 4


def test_never_below_one_minute():
    rng = random.Random(0)
    assert all(sample_actual_duration(2, rng, sigma=1.5) >= 1 for _ in range(5000))