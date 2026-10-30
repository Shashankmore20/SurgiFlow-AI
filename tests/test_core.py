from  surgiflow.sim.core import Simulator, Surgery, Network, Hospital
import pytest 
import json
from pathlib import Path

def make_sim():
    sim = Simulator(Network.single(n_rooms=2))
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
    for room in sim.network.hospitals[0].rooms:
        runs = sorted((r for r in sim.log if r["room"] == room.id),
                      key=lambda r: r["start"])
        for prev, nxt in zip(runs, runs[1:]):
            assert nxt["start"] >= prev["end"]


def test_deterministic():
    assert make_sim().log == make_sim().log

def two_hospitals():
    return Network(
        [Hospital(0, 1), Hospital(1, 1)],
        zones=["Z0", "Z1"],
        travel_time_min=[[5, 12], [12, 5]],
        transfer_time_min=[[0, 10], [10, 0]],
    )


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


def test_travel_and_transfer_lookup():
    net = two_hospitals()
    assert net.travel_time(0, 1) == 12      # zone 0 -> hospital 1
    assert net.transfer_time(0, 1) == 10    # hospital 0 -> hospital 1


def test_bad_tables_rejected():
    hs = lambda: [Hospital(0, 1), Hospital(1, 1)]
    with pytest.raises(ValueError):   # wrong shape (needs 2 zones x 2 hospitals)
        Network(hs(), ["Z0", "Z1"], [[5, 12]])
    with pytest.raises(ValueError):   # negative travel time
        Network(hs(), ["Z0"], [[5, -1]])
    with pytest.raises(ValueError):   # transfer not square
        Network(hs(), ["Z0"], [[5, 12]], [[0, 10]])
    with pytest.raises(ValueError):   # transfer diagonal must be 0
        Network(hs(), ["Z0"], [[5, 12]], [[3, 10], [10, 0]])
    with pytest.raises(ValueError):   # hospital ids must be 0..n-1
        Network([Hospital(1, 1), Hospital(0, 1)], ["Z0"], [[5, 12]])


def test_from_config_loads_both_tables(tmp_path):
    cfg = {
        "hospitals": [
            {"id": 0, "name": "A", "n_or": 2, "n_icu_beds": 3, "capabilities": ["general"]},
            {"id": 1, "name": "B", "n_or": 1, "n_icu_beds": 1, "capabilities": ["general"]},
        ],
        "zones": ["Z0"],
        "travel_time_min": [[5, 12]],
        "transfer_time_min": [[0, 10], [10, 0]],
    }
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg))
    net = Network.from_config(path)
    assert [h.n_rooms for h in net.hospitals] == [2, 1]
    assert net.hospitals[0].recovery_beds == 3
    assert net.travel_time(0, 1) == 12
    assert net.transfer_time(1, 0) == 10


def test_real_base_json_loads():
    path = Path(__file__).resolve().parent.parent / "configs" / "base.json"
    net = Network.from_config(path)
    assert len(net.travel_time_min) == len(net.zones)
    assert all(len(r) == len(net.hospitals) for r in net.travel_time_min)