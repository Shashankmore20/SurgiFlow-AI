"""Tests for the replay data (no matplotlib needed, so these run in CI)."""
from surgiflow.sim.core import Hospital, Network, Simulator, Surgery
from surgiflow.viz.timeline import Timeline, clock_label

CFG = {"horizon_min": 1440, "regular_hours_min": 600}


def one_room_day():
    net = Network([Hospital(0, 1, recovery_beds=1, capabilities=["general"])],
                  ["Z0"], [[20]])
    sim = Simulator(net)
    a = Surgery("A", 60, needs_bed=True, bed_stay=100)
    b = Surgery("B", 30)
    e = Surgery("E", 30, urgency=1, procedure="general")
    sim.add_surgery(a, 0)
    sim.add_surgery(b, 0)
    sim.add_emergency(e, call_time=10, zone=0)     # arrives at 30
    sim.run(until=CFG["horizon_min"])
    return Timeline(sim, [a, b, e], CFG)


def test_busy_and_waiting():
    st = one_room_day().state_at(40)       # A in surgery; B and E waiting
    assert st["busy"] == [1] and st["waiting"] == [2]


def test_ambulance_halfway():
    st = one_room_day().state_at(20)       # call at 10, arrival at 30
    (zone, hospital, frac, urgency), = st["ambulances"]
    assert (zone, hospital, urgency) == (0, 0, 1) and abs(frac - 0.5) < 1e-9


def test_bed_in_use_after_surgery():
    tl = one_room_day()
    assert tl.state_at(59)["beds"] == [0]
    assert tl.state_at(61)["beds"] == [1]      # A moved to a bed at 60
    assert tl.state_at(161)["beds"] == [0]     # stay of 100 ended


def test_clock_label_starts_at_seven():
    assert clock_label(0) == "07:00" and clock_label(600) == "17:00"
    assert clock_label(1080) == "01:00"
