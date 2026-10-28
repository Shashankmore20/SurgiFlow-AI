from  surgiflow.sim.core import Simulator, Surgery


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