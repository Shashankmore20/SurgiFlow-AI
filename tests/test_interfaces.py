import json
from pathlib import Path

from surgiflow.evaluation.objective import objective
from surgiflow.interfaces import LOG_FIELDS
from surgiflow.sim.core import Network, Simulator, Surgery, fifo_policy

BASE = Path(__file__).resolve().parent.parent / "configs" / "base.json"


def test_actual_duration_used_for_end_time():
    sim = Simulator(Network.single(n_rooms=1))
    sim.add_surgery(Surgery("A", 60, actual_duration=80), 0)
    sim.run()
    assert sim.log[0]["planned"] == 60 and sim.log[0]["end"] == 80


def test_kind_follows_emergency_flag():
    assert Surgery("A", 60).kind == "elective"
    assert Surgery("B", 60, emergency=True, urgency=1).kind == "emergency"


def test_log_has_every_shared_field():
    sim = Simulator(Network.single(n_rooms=1))
    sim.add_surgery(Surgery("A", 60), 0)
    sim.run()
    assert set(LOG_FIELDS) <= set(sim.log[0])


def test_policy_can_leave_room_idle():
    sim = Simulator(Network.single(n_rooms=1), policy=lambda hospital, clock: None)
    sim.add_surgery(Surgery("A", 60), 0)
    sim.run()
    assert sim.log == []


def test_policy_sees_hospital_and_picks_most_urgent():
    def most_urgent(hospital, clock):
        return min(hospital.waiting, key=lambda s: s.urgency or 99)

    sim = Simulator(Network.single(n_rooms=1), policy=most_urgent)
    sim.add_surgery(Surgery("blocker", 30), 0)
    sim.add_surgery(Surgery("semi", 30, emergency=True, urgency=3), 1)
    sim.add_surgery(Surgery("critical", 30, emergency=True, urgency=1), 2)
    sim.run()
    order = [r["surgery"] for r in sorted(sim.log, key=lambda r: r["start"])]
    assert order == ["blocker", "critical", "semi"]


def test_simulator_log_scores_with_objective():
    cfg = json.loads(BASE.read_text())
    sim = Simulator(Network.from_config(BASE))
    sim.add_surgery(Surgery("e1", 90, planned_start=0), 0, hospital=0)
    sim.add_emergency(Surgery("x1", 120, urgency=1, procedure="trauma"),
                      call_time=10, zone=2)
    sim.run()
    total, parts = objective(sim.log, cfg)
    assert parts["delay"] == 0 and total > 0


def test_allocation_policy_is_called_at_call_time():
    calls = []

    def send_to_central(patient, network, clock):
        calls.append(clock)
        return 0

    sim = Simulator(Network.from_config(BASE), allocate=send_to_central)
    s = Surgery("x", 60, urgency=1, procedure="general")
    sim.add_emergency(s, call_time=30, zone=2)   # North: nearest is Northside (2)
    sim.run()
    assert calls == [30]
    row = sim.log[0]
    assert row["hospital"] == 0
    assert row["call_time"] == 30 and row["arrival"] == 30 + 22   # North -> Central = 22


def test_allocation_to_incapable_hospital_is_rejected():
    import pytest
    sim = Simulator(Network.from_config(BASE), allocate=lambda p, n, c: 2)
    sim.add_emergency(Surgery("x", 60, procedure="trauma"), call_time=0, zone=0)
    with pytest.raises(ValueError):
        sim.run()


def test_unserved_lists_patients_still_waiting_or_travelling():
    sim = Simulator(Network.from_config(BASE))
    sim.add_surgery(Surgery("done", 60), 0, hospital=0)
    sim.add_surgery(Surgery("late", 60), 1000, hospital=0)              # arrives after stop
    sim.add_emergency(Surgery("x", 60, urgency=2, procedure="general"), 90, zone=0)
    sim.run(until=95)                                                    # x still in the ambulance
    assert sorted(s.id for s in sim.unserved()) == ["late", "x"]


def test_doing_nothing_scores_worse_than_fifo():
    cfg = json.loads(BASE.read_text())

    def run(policy):
        sim = Simulator(Network.from_config(BASE), policy=policy)
        for i in range(4):
            sim.add_surgery(Surgery(f"e{i}", 90, planned_start=90 * i), 90 * i, hospital=0)
        sim.run(until=cfg["horizon_min"])
        return objective(sim.log, cfg, sim.unserved())[0]

    assert run(lambda hospital, clock: None) > run(fifo_policy)
