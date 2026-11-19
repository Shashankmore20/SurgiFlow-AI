import json
import random
from pathlib import Path

from surgiflow.agents.plan import Plan
from surgiflow.sim.generator import generate

CFG = json.loads((Path(__file__).resolve().parents[1] / "configs" / "base.json").read_text())
REGULAR = CFG["regular_hours_min"]


def default_plan(seed):
    electives = generate(CFG, seed).electives
    return electives, Plan.from_electives(electives, CFG)


def walk(plan, rng, steps):
    """Apply `steps` random moves, keeping the allowed ones. Returns every plan visited."""
    visited = []
    for _ in range(steps):
        nxt = plan.neighbour(rng)
        if nxt is not None:
            plan = nxt
            visited.append(plan)
    return visited

def test_default_plan_matches_the_generator():
    for seed in range(10):
        electives, plan = default_plan(seed)
        assert plan.is_valid()
        assert plan.starts() == {s.id: (s.hospital, s.planned_room, s.planned_start)
                                 for s in electives}

def test_moves_keep_every_case_once_and_at_its_hospital():
    electives, plan = default_plan(1)
    home = {s.id: s.hospital for s in electives}
    visited = walk(plan, random.Random(0), 2000)
    assert len(visited) > 100                     # many moves are allowed
    for p in visited:
        assert p.is_valid()
        assert {i: h for i, (h, _, _) in p.starts().items()} == home

def test_no_room_is_planned_past_regular_hours():
    _, plan = default_plan(2)
    for p in walk(plan, random.Random(1), 2000):
        assert all(start + p.duration[i] <= REGULAR for i, (_, _, start) in p.starts().items())

def test_moves_never_change_the_original_plan():
    _, plan = default_plan(3)
    before = plan.starts()
    walk(plan, random.Random(2), 500)
    assert plan.starts() == before

def test_same_seed_gives_the_same_moves():
    _, plan = default_plan(4)
    a = [p.starts() for p in walk(plan, random.Random(7), 300)]
    b = [p.starts() for p in walk(plan, random.Random(7), 300)]
    assert a == b

def times_by_length(plan):
    """What a plan really decides: which LENGTHS of case start when, per room.
    Swapping two cases of the same length leaves this unchanged."""
    return sorted((h, r, start, plan.duration[i]) for i, (h, r, start) in plan.starts().items())


def test_every_allowed_move_really_changes_the_plan():
    _, plan = default_plan(1)          # seed 1 has rooms at 450, so moves are possible
    rng = random.Random(3)
    for move in (plan._swap_within, plan._swap_between, plan._move):
        allowed = [p for p in (move(rng) for _ in range(200)) if p is not None]
        assert allowed, move.__name__
        assert all(times_by_length(p) != times_by_length(plan) for p in allowed)

def test_full_day_allows_reordering_only():
    _, plan = default_plan(0)          # seed 0: every room planned at 540
    assert all(plan.load(h, r) == 540 for h, rooms in enumerate(plan.rooms)
               for r in range(len(rooms)))
    rng = random.Random(0)
    assert all(plan._move(rng) is None for _ in range(200))           # +90 -> 630 > 600
    assert all(plan._swap_between(rng) is None for _ in range(200))   # 90<->180 also overfills
    assert any(plan._swap_within(rng) is not None for _ in range(200))

def test_single_room_can_only_reorder():
    plan = Plan(rooms=((("a", "b"),),), duration={"a": 60, "b": 90}, limit=600)
    rng = random.Random(0)
    assert plan._swap_between(rng) is None and plan._move(rng) is None
    assert plan._swap_within(rng).starts() == {"b": (0, 0, 0), "a": (0, 0, 90)}

def test_move_that_overfills_a_room_is_rejected():
    plan = Plan(rooms=((("a",), ("b",)),), duration={"a": 300, "b": 400}, limit=600)
    rng = random.Random(0)
    assert all(plan._move(rng) is None for _ in range(20))              # 700 > 600
    assert all(plan._swap_between(rng) is not None for _ in range(20))  # swap keeps 300 / 400