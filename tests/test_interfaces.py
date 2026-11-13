import json
from pathlib import Path

from surgiflow.evaluation.objective import objective
from surgiflow.interfaces import LOG_FIELDS
from surgiflow.sim.core import Network, Simulator, Surgery

BASE = Path(__file__).resolve().parent.parent / "configs" / "base.json"


def test_expected_duration_defaults_to_true_duration():
    s = Surgery("A", 90)
    assert s.expected_duration == 90
    assert Surgery("B", 90, expected_duration=60).expected_duration == 60


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
    sim.add_surgery(Surgery("x1", 120, emergency=True, urgency=1, procedure="trauma"),
                    10, hospital=0)
    sim.run()
    total, parts = objective(sim.log, cfg)
    assert parts["delay"] == 0 and total > 0
