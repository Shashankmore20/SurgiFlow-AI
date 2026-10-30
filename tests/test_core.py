from  surgiflow.sim.core import Simulator, Surgery, Network, Hospital
import pytest 

def make_sim():
    sim = Simulator(n_rooms=2)
    for sid, dur in [("A", 60), ("B", 90), ("C", 30)]:
        sim.add_surgery(Surgery(id=sid, duration=dur), arrival_time=0)
    sim.run()
    return sim


def by_id(sim):
    return {r["surgery"]: r for r in sim.log}


def test_hand_checked_schedule():
    r = by_id(make_sim())
    assert (r["A"]["start"], r["A"]["end"]) == (0, 60)
    assert (r["B"]["start"], r["B"]["end"]) == (0, 90)
    assert (r["C"]["start"], r["C"]["end"]) == (60, 90)
    assert r["C"]["room"] == r["A"]["room"]


def test_no_room_overlap():
    sim = make_sim()
    for room in sim.rooms:
        runs = sorted((r for r in sim.log if r["room"] == room.id),
                      key=lambda r: r["start"])
        for prev, nxt in zip(runs, runs[1:]):
            assert nxt["start"] >= prev["end"]


def test_deterministic():
    assert make_sim().log == make_sim().log

def two_hospitals():
    return Network([Hospital(0, 1), Hospital(1, 1)], [[0, 10], [10, 0]])


def test_hospitals_run_independently():
    sim = Simulator(two_hospitals())
    sim.add_surgery(Surgery("A", 60), 0, hospital=0)
    sim.add_surgery(Surgery("B", 60), 0, hospital=1)
    sim.run()
    r = by_id(sim)
    assert r["A"]["start"] == 0 and r["B"]["start"] == 0
    assert (r["A"]["hospital"], r["B"]["hospital"]) == (0, 1)


def test_queues_are_per_hospital():
    sim = Simulator(two_hospitals())
    sim.add_surgery(Surgery("A", 60), 0, hospital=0)
    sim.add_surgery(Surgery("B", 30), 0, hospital=0)
    sim.add_surgery(Surgery("C", 30), 0, hospital=1)
    sim.run()
    r = by_id(sim)
    assert r["B"]["start"] == 60   # waits behind A at hospital 0
    assert r["C"]["start"] == 0    # hospital 1 is free


def test_travel_time_lookup():
    assert two_hospitals().travel_time(0, 1) == 10

def test_bad_travel_matrix_rejected():
    with pytest.raises(ValueError):
        Network([Hospital(0, 1), Hospital(1, 1)], [[0, 10]])
    with pytest.raises(ValueError):
        Network([Hospital(0, 1)], [[5]])