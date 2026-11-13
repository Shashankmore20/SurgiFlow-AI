import pytest

from surgiflow.evaluation.objective import objective, objective_components
from surgiflow.sim.core import Surgery

CONFIG = {
    "regular_hours_min": 600,
    "hospitals": [{"id": 0, "n_or": 1}, {"id": 1, "n_or": 1}],
    "emergencies": {"urgency_levels": [
        {"level": 1, "max_wait_min": 60},
        {"level": 2, "max_wait_min": 240},
        {"level": 3, "max_wait_min": 1440},
    ]},
    "objective": {
        "urgency_wait_multiplier": {"1": 4, "2": 2, "3": 1},
        "weights": {"wait": 1, "delay": 10, "overtime": 0.5,
                    "disruption": 0.2, "imbalance": 100, "transfers": 15},
    },
}


def emergency(urgency, arrival, start, end, hospital=0, room=0, transfers=0):
    return dict(kind="emergency", urgency=urgency, arrival=arrival, start=start,
                end=end, hospital=hospital, room=room, transfers=transfers)


def elective(planned, start, end, hospital=0, room=0):
    return dict(kind="elective", urgency=None, planned_start=planned,
                start=start, end=end, hospital=hospital, room=room)


def test_critical_patient_past_deadline():
    # waited 90 min, critical limit is 60 -> 30 min late, wait weighted x4
    parts = objective_components([emergency(1, 0, 90, 150)], CONFIG)
    assert parts["wait"] == 360
    assert parts["delay"] == 30


def test_on_time_patient_has_no_delay():
    parts = objective_components([emergency(2, 0, 100, 200)], CONFIG)
    assert parts["delay"] == 0


def test_overtime_counts_last_surgery_per_room():
    recs = [elective(500, 500, 650, room=0), elective(0, 0, 100, room=1)]
    assert objective_components(recs, CONFIG)["overtime"] == 50


def test_disruption_is_minutes_moved():
    recs = [elective(100, 160, 250)]
    assert objective_components(recs, CONFIG)["disruption"] == 60


def test_balanced_hospitals_have_zero_imbalance():
    recs = [elective(0, 0, 300, hospital=0), elective(0, 0, 300, hospital=1)]
    assert objective_components(recs, CONFIG)["imbalance"] == 0


def test_total_is_weighted_sum():
    recs = [emergency(1, 0, 90, 150, transfers=1)]
    total, parts = objective(recs, CONFIG)
    # wait 360*1 + delay 30*10 + transfers 1*15 + imbalance (0.1 util std)*100
    assert total == pytest.approx(360 + 300 + 15 + parts["imbalance"] * 100)


# ---- D10: overtime only for the regular day, unserved patients, patient count ----

def test_night_surgery_is_not_overtime():
    # started at 700, after regular hours (600): on-call work, not overtime
    assert objective_components([emergency(2, 650, 700, 900)], CONFIG)["overtime"] == 0


def test_surgery_started_before_600_counts_overtime():
    assert objective_components([elective(550, 550, 650)], CONFIG)["overtime"] == 50


def test_bed_blocked_room_counts_until_released():
    rec = elective(500, 500, 590)
    rec["room_release"] = 640          # patient stuck in the OR waiting for a bed
    assert objective_components([rec], CONFIG)["overtime"] == 40


def test_unserved_emergency_keeps_waiting_until_horizon():
    cfg = {**CONFIG, "horizon_min": 1440}
    s = Surgery("x", 60, emergency=True, urgency=1, call_time=1340)
    parts = objective_components([], cfg, unserved=[s])
    assert parts["wait"] == 4 * 100           # waited 100 min, critical x4
    assert parts["delay"] == 40               # 100 - 60 min limit
    assert parts["unserved"] == 1 and parts["patients"] == 1


def test_unserved_elective_is_disrupted_and_penalized():
    cfg = {**CONFIG, "horizon_min": 1440}
    cfg["objective"] = {**CONFIG["objective"],
                        "weights": {**CONFIG["objective"]["weights"], "unserved": 200}}
    s = Surgery("e", 90, planned_start=1000)
    total, parts = objective([], cfg, unserved=[s])
    assert parts["disruption"] == 440
    assert total == pytest.approx(0.2 * 440 + 200)


def test_patients_is_reported_but_not_weighted():
    total, parts = objective([elective(0, 0, 100)], CONFIG)
    assert parts["patients"] == 1
    assert "patients" not in CONFIG["objective"]["weights"]
