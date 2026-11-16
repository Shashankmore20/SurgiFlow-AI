"""Tests for three small simulator changes:
  1. a cancel that fires BEFORE the patient arrives is honoured
  2. Surgery.start_time is set when surgery begins
  3. Hospital.inbound lists patients who were allocated there but are still travelling
"""
from pathlib import Path

from surgiflow.sim.core import Network, Simulator, Surgery

BASE = Path(__file__).resolve().parent.parent / "configs" / "base.json"


# ---- 1. cancel before arrival ------------------------------------------------

def test_cancel_before_arrival_is_not_operated_on():
    sim = Simulator(Network.single(n_rooms=1))
    s = Surgery("A", 60, planned_start=100)
    sim.add_surgery(s, arrival_time=100)
    sim.cancel_surgery(s, time=50)          # cancelled before it arrives
    sim.run()
    assert sim.log == []
    assert sim.cancellations == [{"surgery": "A", "hospital": 0, "time": 50}]


def test_cancel_before_arrival_frees_the_room_for_others():
    # P is booked for minute 100 and cancels at 50; Q arrives at 110.
    sim = Simulator(Network.single(n_rooms=1))
    p = Surgery("P", 60, planned_start=100)
    q = Surgery("Q", 30, planned_start=110)
    sim.add_surgery(p, arrival_time=100)
    sim.add_surgery(q, arrival_time=110)
    sim.cancel_surgery(p, time=50)
    sim.run()
    rows = {r["surgery"]: r for r in sim.log}
    assert set(rows) == {"Q"}
    assert rows["Q"]["start"] == 110        # no wait: P never used the room


def test_cancelled_before_arrival_is_not_unserved():
    sim = Simulator(Network.single(n_rooms=1))
    s = Surgery("A", 60, planned_start=100)
    sim.add_surgery(s, arrival_time=100)
    sim.cancel_surgery(s, time=50)
    sim.run(until=60)                       # stop before the arrival event
    assert sim.unserved() == []


def test_cancelling_twice_is_recorded_once():
    sim = Simulator(Network.single(n_rooms=1))
    s = Surgery("A", 60)
    sim.add_surgery(s, arrival_time=100)
    sim.cancel_surgery(s, time=10)
    sim.cancel_surgery(s, time=20)
    sim.run()
    assert len(sim.cancellations) == 1


def test_cancel_during_the_ambulance_ride_drops_the_emergency():
    sim = Simulator(Network.from_config(BASE))
    e = Surgery("x", 60, urgency=2, procedure="general")
    sim.add_emergency(e, call_time=0, zone=0)    # Downtown -> Central is 8 min
    sim.cancel_surgery(e, time=3)                # cancelled while travelling
    sim.run()
    assert sim.log == []
    assert sim.unserved() == []
    assert sim.network.hospitals[0].inbound == []


# ---- 2. start_time -----------------------------------------------------------

def test_start_time_matches_the_log_and_is_none_while_waiting():
    sim = Simulator(Network.single(n_rooms=1))
    a, b = Surgery("A", 60), Surgery("B", 30)
    sim.add_surgery(a, 0)
    sim.add_surgery(b, 0)
    sim.run(until=10)
    assert a.start_time == 0                # in the room
    assert b.start_time is None             # still waiting
    sim.run()
    rows = {r["surgery"]: r for r in sim.log}
    assert a.start_time == rows["A"]["start"]
    assert b.start_time == rows["B"]["start"] == 60


def test_start_time_lets_a_policy_estimate_remaining_time():
    seen = {}

    def spy(patient, network, clock):
        running = network.hospitals[0].rooms[0].current
        if running is not None:
            seen["remaining"] = running.start_time + running.duration - clock
        return network.nearest_capable(patient.zone, patient.procedure)

    sim = Simulator(Network.from_config(BASE), allocate=spy)
    sim.add_surgery(Surgery("blocker", 120), 0, hospital=0)   # starts at 0, planned 120
    sim.add_emergency(Surgery("x", 60, urgency=2, procedure="general"), call_time=30, zone=0)
    sim.run()
    assert seen["remaining"] == 90          # 120 planned - 30 already elapsed


# ---- 3. inbound --------------------------------------------------------------

def test_inbound_lists_patients_still_travelling():
    sim = Simulator(Network.from_config(BASE))
    for i in range(3):                      # three calls in the same minute
        sim.add_emergency(Surgery(f"x{i}", 60, urgency=2, procedure="general"),
                          call_time=0, zone=0)
    sim.run(until=0)                        # calls handled, nobody has arrived yet
    inbound = [s.id for h in sim.network.hospitals for s in h.inbound]
    assert sorted(inbound) == ["x0", "x1", "x2"]
    sim.run()                               # ambulances arrive
    assert all(h.inbound == [] for h in sim.network.hospitals)


def test_allocation_policy_can_see_earlier_calls_in_transit():
    seen = []

    def spy(patient, network, clock):
        seen.append(sum(len(h.inbound) for h in network.hospitals))
        return network.nearest_capable(patient.zone, patient.procedure)

    sim = Simulator(Network.from_config(BASE), allocate=spy)
    for i in range(3):
        sim.add_emergency(Surgery(f"x{i}", 60, urgency=2, procedure="general"),
                          call_time=i, zone=0)
    sim.run()
    assert seen == [0, 1, 2]                # each call sees the ones before it


def test_emergency_cancelled_before_call_has_no_hospital():
    sim = Simulator(Network.single(1))
    s = Surgery("E1", 60, urgency=1)
    sim.add_emergency(s, call_time=100, zone=0)
    sim.cancel_surgery(s, 50)
    sim.run()
    assert sim.cancellations == [{"surgery": "E1", "hospital": None, "time": 50}]