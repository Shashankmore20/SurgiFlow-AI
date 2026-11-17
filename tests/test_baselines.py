"""Tests for the baseline policies in surgiflow.agents.baselines (tasks 2.7 and 2.8).

urgency_first_policy (2.7, scheduling) rule, in priority order:
  1. lower urgency number first (1 critical, 2 urgent, 3 semi-urgent)
  2. electives (urgency None) after every emergency
  3. ties: earlier arrival first, then lower id (so results are deterministic)
It must never return None while someone waits, and never modify hospital.waiting.

capacity_aware_policy (2.8, allocation) rule:
  1. only hospitals that can do the patient's procedure
  2. pick the one where surgery is expected to start soonest
     (travel + estimated queue wait, planned durations only; everyone already
     waiting or inbound there is assumed to go first)
  3. ties: nearer hospital first, then lower id
It must never read actual_duration, and never modify the network.
"""
import copy
from pathlib import Path

import pytest

from surgiflow.agents.baselines import capacity_aware_policy, urgency_first_policy
from surgiflow.sim.core import (Hospital, Network, Simulator, Surgery,
                                fifo_policy, nearest_capable_policy)

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "base.json"
CENTRAL, RIVERSIDE, NORTHSIDE = 0, 1, 2   # hospital ids in base.json
DOWNTOWN = 0                              # zone; travel from it: Central 8, Riverside 15, Northside 20


# =====================================================================
# Task 2.7: urgency_first_policy (scheduling)
# =====================================================================

# ---------- helpers ----------

def hosp(*surgeries):
    """A one-room hospital whose waiting list is exactly these patients, in this order."""
    h = Hospital(0, 1)
    h.waiting = list(surgeries)
    return h


def s(id, urgency=None, arrival=0, duration=60):
    """A patient. urgency=None means elective. `arrival` is the minute they reached the hospital."""
    return Surgery(id=id, duration=duration, urgency=urgency, arrival=arrival)


# ---------- unit tests: the choosing rule itself ----------

def test_critical_beats_older_elective_and_urgent():
    """Urgency beats waiting time: S5 (critical, arrived last) goes before
    E7 (elective, waited longest) and S2 (semi-urgent)."""
    h = hosp(s("E7", None, 90), s("S2", 3, 95), s("S5", 1, 98))
    assert urgency_first_policy(h, 100).id == "S5"


def test_same_urgency_earlier_arrival_wins():
    """Two critical patients: the one who reached the hospital first goes first,
    even though B is listed first in the queue."""
    h = hosp(s("B", 1, 99), s("A", 1, 98))
    assert urgency_first_policy(h, 100).id == "A"


def test_same_urgency_and_arrival_lower_id_wins_every_time():
    """Full tie on urgency and arrival: the id decides, so the answer is
    deterministic. Same input, same pick, every call."""
    h = hosp(s("B", 2, 50), s("A", 2, 50))
    assert [urgency_first_policy(h, 100).id for _ in range(3)] == ["A", "A", "A"]


def test_electives_only_earliest_arrival_wins():
    """With no emergencies waiting, the policy behaves like FIFO among electives."""
    h = hosp(s("E2", None, 30), s("E1", None, 10))
    assert urgency_first_policy(h, 100).id == "E1"


def test_empty_queue_returns_none():
    """Nobody waiting means nothing to choose. Return None instead of crashing
    (min() on an empty list would raise)."""
    assert urgency_first_policy(hosp(), 0) is None


def test_does_not_modify_waiting():
    """Policies only choose. The simulator removes the patient afterwards (D9 rule).
    The list must keep the same patients in the same order."""
    h = hosp(s("E7", None, 90), s("S5", 1, 98), s("S2", 3, 95))
    before = list(h.waiting)
    urgency_first_policy(h, 100)
    assert h.waiting == before


# ---------- integration tests: policy plugged into the real Simulator ----------

def run_scenario(policy):
    """One room, zero travel time (Network.single). Timeline:
         0   BLOCK (elective, 100 min) arrives and takes the room until minute 100
         10  ELECTIVE arrives and waits
         50  CRIT (critical emergency, 30 min) is called and arrives immediately, waits
         100 the room frees: the policy chooses between ELECTIVE and CRIT
    Returns {surgery id: start minute}."""
    sim = Simulator(Network.single(1), policy=policy)
    sim.add_surgery(s("BLOCK", None, 0, duration=100), arrival_time=0)
    sim.add_surgery(s("ELECTIVE", None, 10), arrival_time=10)
    sim.add_emergency(s("CRIT", 1, duration=30), call_time=50, zone=0)
    sim.run()
    return {r["surgery"]: r["start"] for r in sim.log}


def test_in_simulator_critical_goes_before_waiting_elective():
    """Urgency-first: CRIT takes the room at 100 and ends at 130,
    then ELECTIVE starts at 130."""
    start = run_scenario(urgency_first_policy)
    assert start["CRIT"] == 100
    assert start["ELECTIVE"] == 130


def test_same_scenario_under_fifo_is_different():
    """Control: the same day under FIFO picks the older ELECTIVE first (start 100),
    so CRIT waits until 160. This shows the test above can only pass because of
    the urgency rule, not by accident."""
    start = run_scenario(fifo_policy)
    assert start["ELECTIVE"] == 100 and start["CRIT"] == 160


# =====================================================================
# Task 2.8: capacity_aware_policy (allocation)
# =====================================================================

# ---------- helpers ----------

def net():
    """The real 3-hospital network from base.json, with nobody in it."""
    return Network.from_config(CONFIG_PATH)


def occupy(hospital, room, free_at, now=300):
    """Put a surgery in a room that started an hour before `now` and whose
    PLANNED end is minute `free_at` (the only end an allocator may look at)."""
    busy = Surgery(f"busy-{hospital.id}-{room}", duration=free_at - (now - 60))
    busy.start_time = now - 60
    hospital.rooms[room].current = busy


def call(procedure="general", zone=DOWNTOWN, id="NEW"):
    """A new emergency call (urgent, 90 planned minutes) from `zone`."""
    return Surgery(id, duration=90, urgency=2, emergency=True, procedure=procedure, zone=zone)


def jammed_central_free_riverside():
    """The network at minute 300, with the nearest hospital overloaded:
         Central    rooms free at 360/390/420/450, 3 patients waiting (90 min each)
         Riverside  one room busy until 310, two rooms free
         Northside  both rooms busy until 400
    Estimated call-to-surgery for a general call from Downtown:
         Central 150 min, Riverside 15 min, Northside 100 min."""
    n = net()
    for room, free_at in enumerate([360, 390, 420, 450]):
        occupy(n.hospitals[CENTRAL], room, free_at)
    n.hospitals[CENTRAL].waiting = [s(f"W{i}", None, 250, duration=90) for i in range(3)]
    occupy(n.hospitals[RIVERSIDE], 0, 310)
    occupy(n.hospitals[NORTHSIDE], 0, 400)
    occupy(n.hospitals[NORTHSIDE], 1, 400)
    return n


# ---------- unit tests: the choosing rule itself ----------

def test_empty_network_behaves_like_nearest():
    """Nobody anywhere: no queue to avoid, so the nearest capable hospital wins,
    from every zone and for every procedure."""
    n = net()
    for zone in range(4):
        for proc in ("general", "cardiac", "trauma"):
            p = call(proc, zone)
            assert capacity_aware_policy(p, n, 0) == nearest_capable_policy(p, n, 0)


def test_avoids_jammed_nearest_hospital():
    """Central is nearest (8 min) but the estimated start there is minute 450
    (150 min away). Riverside is 15 min away with a free room: start at 315.
    Capacity-aware picks Riverside; nearest-capable (the control) picks Central."""
    n = jammed_central_free_riverside()
    assert nearest_capable_policy(call(), n, 300) == CENTRAL
    assert capacity_aware_policy(call(), n, 300) == RIVERSIDE


def test_trauma_always_goes_to_the_only_capable_hospital():
    """Only Central does trauma, so it goes there however busy Central is."""
    n = jammed_central_free_riverside()
    assert capacity_aware_policy(call("trauma"), n, 300) == CENTRAL


def test_cardiac_never_goes_to_northside():
    """Northside is empty and Central/Riverside are full, but Northside can't
    do cardiac, so it is never chosen."""
    n = net()
    for h in (CENTRAL, RIVERSIDE):
        for room in range(len(n.hospitals[h].rooms)):
            occupy(n.hospitals[h], room, 600)
    assert capacity_aware_policy(call("cardiac"), n, 300) in (CENTRAL, RIVERSIDE)


def test_inbound_patients_count_as_ahead():
    """Central has ONE free room left. With nobody inbound it is the best choice.
    Add one ambulance already heading there and that room is spoken for,
    so the same call now goes to Riverside."""
    n = net()
    for room in range(3):                                      # room 3 stays free
        occupy(n.hospitals[CENTRAL], room, 500)
    assert capacity_aware_policy(call(), n, 300) == CENTRAL
    n.hospitals[CENTRAL].inbound = [s("AMB", 1, duration=120)]
    assert capacity_aware_policy(call(), n, 300) == RIVERSIDE


def test_overrunning_surgery_counts_as_free_now_not_in_the_past():
    """All Central rooms hold surgeries planned to end at 250, and it is now 300
    (they are overrunning). The rooms count as free now, not free in the past,
    so the estimated start is the arrival (308) and Central is still chosen."""
    n = net()
    for room in range(4):
        occupy(n.hospitals[CENTRAL], room, 250)
    assert capacity_aware_policy(call(), n, 300) == CENTRAL


def test_tie_goes_to_nearer_hospital():
    """Every room everywhere frees at 400, after any ambulance would arrive, so
    all three hospitals give the same estimate. The nearer one, Central, wins."""
    n = net()
    for h, rooms in ((CENTRAL, 4), (RIVERSIDE, 3), (NORTHSIDE, 2)):
        for room in range(rooms):
            occupy(n.hospitals[h], room, 400)
    assert capacity_aware_policy(call(), n, 300) == CENTRAL


def test_no_capable_hospital_raises():
    """A procedure no hospital offers is a setup error: raise a clear ValueError
    instead of sending the patient somewhere that can't operate."""
    with pytest.raises(ValueError):
        capacity_aware_policy(call("neuro"), net(), 0)


def test_allocation_does_not_modify_the_network():
    """Allocation policies only read the network (D9 rule). Every hospital's
    rooms, waiting list and inbound list are unchanged after the call."""
    n = jammed_central_free_riverside()
    before = copy.deepcopy(n.hospitals)
    capacity_aware_policy(call(), n, 300)
    assert n.hospitals == before


# ---------- integration tests: policy plugged into the real Simulator ----------

def run_three_calls(allocate):
    """Three one-room hospitals that all do general surgery, at 5/10/15 minutes
    from the only zone. Three calls (P0, P1, P2; 120 min each) come in at minute 0.
    Returns {surgery id: (hospital, start minute)}."""
    hospitals = [Hospital(i, 1, capabilities=["general"]) for i in range(3)]
    sim = Simulator(Network(hospitals, ["Z"], [[5, 10, 15]]), allocate=allocate)
    for i in range(3):
        sim.add_emergency(s(f"P{i}", 2, duration=120), call_time=0, zone=0)
    sim.run()
    return {r["surgery"]: (r["hospital"], r["start"]) for r in sim.log}


def test_in_simulator_three_calls_spread_out():
    """Capacity-aware sees the earlier ambulances (inbound) and sends each call
    to a different hospital, so the last patient starts at minute 15."""
    assert run_three_calls(capacity_aware_policy) == {
        "P0": (0, 5), "P1": (1, 10), "P2": (2, 15)}


def test_same_three_calls_under_nearest_all_queue_at_one_hospital():
    """Control: nearest-capable sends all three to hospital 0, where they queue
    for its single room, so the last patient starts at minute 245."""
    assert run_three_calls(nearest_capable_policy) == {
        "P0": (0, 5), "P1": (0, 125), "P2": (0, 245)}