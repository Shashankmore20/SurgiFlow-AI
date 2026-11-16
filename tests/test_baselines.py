"""Tests for the baseline policies in surgiflow.agents.baselines (task 2.7).

urgency_first_policy rule, in priority order:
  1. lower urgency number first (1 critical, 2 urgent, 3 semi-urgent)
  2. electives (urgency None) after every emergency
  3. ties: earlier arrival first, then lower id (so results are deterministic)
It must never return None while someone waits, and never modify hospital.waiting.
"""
from surgiflow.agents.baselines import urgency_first_policy
from surgiflow.sim.core import Hospital, Network, Simulator, Surgery, fifo_policy


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