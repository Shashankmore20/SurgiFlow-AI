import random

from surgiflow.sim.core import Hospital, Network, Simulator, Surgery
from surgiflow.sim.emergencies import generate_emergencies, schedule_emergencies

CFG = {
    "horizon_min": 1440,
    "zones": ["Downtown", "East", "North", "Suburbs"],
    "procedures": {
        "general": {"mean_duration_min": 90},
        "cardiac": {"mean_duration_min": 180},
        "trauma": {"mean_duration_min": 150},
    },
    "emergencies": {
        "arrivals_per_day": 12,
        "urgency_levels": [
            {"level": 1, "label": "critical", "max_wait_min": 60, "prob": 0.2},
            {"level": 2, "label": "urgent", "max_wait_min": 240, "prob": 0.4},
            {"level": 3, "label": "semi-urgent", "max_wait_min": 1440, "prob": 0.4},
        ],
    },
}


def network():
    hospitals = [
        Hospital(0, 2, capabilities=["trauma", "cardiac", "general"]),
        Hospital(1, 2, capabilities=["cardiac", "general"]),
        Hospital(2, 2, capabilities=["general"]),
    ]
    travel = [[8, 15, 20], [18, 7, 25], [22, 26, 9], [30, 20, 15]]
    return Network(hospitals, CFG["zones"], travel)


def test_nearest_capable_respects_capability():
    net = network()
    assert net.nearest_capable(2, "general") == 2    # North: Northside is closest
    assert net.nearest_capable(2, "cardiac") == 0    # Northside cannot do cardiac
    assert net.nearest_capable(0, "trauma") == 0     # only hospital 0 does trauma
    assert net.nearest_capable(3, "cardiac") == 1


def test_emergency_arrives_after_travel_time():
    sim = Simulator(network())
    s = Surgery("E0", 60, procedure="general")
    h = sim.add_emergency(s, call_time=100, zone=0)
    sim.run()
    row = sim.log[0]
    assert h == 0
    assert row["call_time"] == 100 and row["arrival"] == 108 and row["start"] == 108
    assert row["emergency"] is True


def test_cancel_removes_waiting_surgery():
    sim = Simulator(Network.single(n_rooms=1))
    sim.add_surgery(Surgery("A", 60), 0)
    b = Surgery("B", 30)
    sim.add_surgery(b, 0)
    sim.cancel_surgery(b, 30)
    sim.run()
    assert [r["surgery"] for r in sim.log] == ["A"]
    assert sim.cancellations == [{"surgery": "B", "hospital": 0, "time": 30}]


def test_cancel_too_late_does_nothing():
    sim = Simulator(Network.single(n_rooms=1))
    a = Surgery("A", 60)
    sim.add_surgery(a, 0)
    sim.cancel_surgery(a, 30)   # already in the room
    sim.run()
    assert [r["surgery"] for r in sim.log] == ["A"]
    assert sim.cancellations == []


def test_generator_is_reproducible_and_sane():
    a = generate_emergencies(CFG, random.Random(5))
    b = generate_emergencies(CFG, random.Random(5))
    assert [(t, z, s.id, s.procedure, s.actual_duration) for t, z, s in a] == \
           [(t, z, s.id, s.procedure, s.actual_duration) for t, z, s in b]
    times = [t for t, _, _ in a]
    assert times == sorted(times) and all(0 <= t < 1440 for t in times)
    assert all(s.priority in (1, 2, 3) and s.emergency for _, _, s in a)
    assert all(0 <= z < 4 for _, z, _ in a)


def test_priority_is_higher_for_more_urgent():
    by_wait = {}
    for seed in range(20):
        for _, _, s in generate_emergencies(CFG, random.Random(seed)):
            by_wait[s.max_wait] = s.priority
    assert by_wait[60] == 3 and by_wait[240] == 2 and by_wait[1440] == 1


def test_average_arrivals_per_day():
    counts = [len(generate_emergencies(CFG, random.Random(s))) for s in range(300)]
    assert abs(sum(counts) / len(counts) - 12) < 1


def test_schedule_emergencies_runs_end_to_end():
    sim = Simulator(network())
    schedule_emergencies(sim, CFG, random.Random(1))
    sim.run()
    assert len(sim.log) > 0
    assert all(r["emergency"] for r in sim.log)