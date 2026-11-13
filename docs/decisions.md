# Decision Log

Each entry: what we decided, why, alternatives, and when to revisit.
Configs that have produced results are never edited; add a new config instead.

## D1 — Repository structure
**Decision:** `src/surgiflow/{sim,agents,evaluation}`, plus `configs/`, `scripts/`, `tests/`, `report/`, `results/`, `docs/`.
**Why:** Simulator, agents, and evaluation are separate pieces that different people own.
**Revisit:** If a module grows large enough to split.

## D2 — Environment
**Decision:** Conda env `FAI`, Python 3.14, the course `requirements.txt` unchanged, plus a "project additions" section with pinned versions.
**Why:** Same environment as the course assignments; everyone already has it.

## D3 — Git workflow
**Decision:** One long-lived branch per person, PRs into protected `main` (0 required approvals), "Create a merge commit" only, sync from main at the start of each session.
**Why:** Simple for a 3-person team working at different hours.
**Alternatives:** One branch per task; required approvals.
**Revisit:** If unreviewed merges start breaking shared code, require 1 approval.

## D4 — Compute
**Decision:** Run everything locally (M1 Pro, CPU). No Explorer cluster.
**Why:** Tabular RL and SA/GA are CPU-bound; a GPU doesn't help. Parallelize across seeds with `multiprocessing`; use `caffeinate` for long runs; checkpoint training.
**Revisit:** If full experiments take too long on our laptops.

## D5 — Scope (`configs/base.json`)
**Decision:** 3 hospitals with different capabilities, 4 zones with a fixed travel-time matrix, 1-day horizon in minutes (600 regular OR minutes, beyond that is overtime), electives at 85% utilization, about 12 emergencies/day across 3 urgency levels.
**Why:** Small enough to debug and train quickly; capability differences make "nearest hospital" a poor policy, which is the gap the proposal targets.
**Alternatives:** Real road maps (too complex); identical hospitals (allocation becomes trivial).
**Revisit:** Once baselines and first methods work → add `large.json` / `surge.json`.

## D6 — Discrete-event simulator core (task 2.1)
**Decision:** A heap of timed events (ARRIVAL, END). The clock jumps to the earliest event; ties keep insertion order. After every event, free rooms are filled by a pluggable scheduling policy (signature updated in D9) (FIFO by default). Output is a log of surgery, room, arrival, start, end.
**Why:** Exact times and no wasted steps, so it's fast enough for RL training. The policy plug-in lets SA/GA/RL replace FIFO without changing the engine.
**Alternatives:** Fixed time steps (simpler, but slower and less precise).
**Revisit:** The policy will likely need more state (rooms, hospital, beds); defined in task 1.5.

## D7 — Inter-hospital transfers
**Decision:** Add `transfer_time_min` (3x3 hospital -> hospital) to `base.json`, alongside the 4x3 zone -> hospital `travel_time_min`. Only waiting patients (not mid-surgery) can be transferred, only to a hospital capable of their procedure. Transfer time adds to their wait, and the objective adds a small per-transfer penalty. Transferring is a policy action.
**Why:** An overloaded hospital can hand patients to one with free capacity, which is the network-coordination gap in the proposal.
**Alternatives:** No transfers (allocation only at arrival); post-surgery ICU transfers (deferred to task 2.5).
**Revisit:** When setting objective weights (1.6), tune the transfer penalty.

## D8 — Objective function (task 1.6)
**Decision:** Cost = 1·wait + 10·delay + 0.5·overtime + 0.2·disruption + 100·imbalance + 15·transfers (weights in `base.json`). Emergency wait is multiplied by urgency (critical x4, urgent x2, semi-urgent x1). All components are also reported separately.
**Why:** Priority order: missed deadlines > critical waits > other waits > overtime > disruption and balance. One shared function makes every method's score comparable.
**Alternatives:** Optimizing each metric separately (multi-objective, hard to compare); unweighted sum (minutes of overtime would count as much as minutes a critical patient waits).
**Revisit:** Sensitivity analysis on the weights once methods are working.

## D9 — Shared interfaces (task 1.5)
**Decision:**
- `Surgery` is the one shared patient type. `duration` is the planned length policies see; `actual_duration` is the true, hidden length (2.3). Also: `urgency`, `procedure`, `zone`, `call_time`, `max_wait`, `needs_bed`, `bed_stay`, `planned_room`, `planned_start`, `transfers`.
- Generator (2.6): `generate(config, seed) -> Instance` (electives + emergencies). All randomness lives here, including later overruns, cancellations and surges.
- Simulator: `Instance` + policies -> log. Deterministic.
- Scheduling policy: `policy(hospital, clock) -> Surgery | None` (None keeps the room free).
- Allocation policy: `allocate(patient, network, clock) -> hospital id`, called at the emergency's call time (CALL event); default is nearest capable hospital. The patient arrives after the travel time.
- Every log record has the fields in `interfaces.LOG_FIELDS`, which the objective reads.
**Rules:** policies never read `actual_duration`; policies never modify the network; an emergency's wait is measured from `call_time` (includes travel); an elective's `arrival` is its `planned_start`.
**Update:** names aligned with Zaiba's 2.3–2.5 work (`actual_duration`, `needs_bed`, `call_time`) when merging PR #52.
**Why:** Lets generator, simulator and policies be built and tested in parallel; the same seed gives every method identical inputs.
**Alternatives:** Randomness inside the simulator (methods would face different days; harder to test).
**Revisit:** Add the transfer hook in 2.11.


## D10 — Overtime and unserved patients in the objective
**Decision:**
- Overtime counts only surgeries that *started* during regular hours (before `regular_hours_min`) and ran past it, measured until the room is actually free (`room_release`, so bed-blocking counts). Surgeries started after regular hours are on-call work and don't count.
- Patients who never get surgery (`sim.unserved()`: still waiting or still travelling when the run stops) are scored: emergencies keep accumulating wait and delay until `horizon_min`; electives count as disrupted until `horizon_min`. Every unserved patient also costs a flat 200 (`weights.unserved`).
- The objective also reports `patients` (served + unserved), not weighted, for per-patient averages. Raw totals are only compared within the same config.
**Why:** In a test day (seed 1, emergencies only), night emergencies made overtime 78% of the cost (1733 of 1110 total); with the fix it is 135 of 311. Without the unserved penalty, a policy that never operates would score zero disruption and zero overtime.
**Choosing 200:** more than the overtime cost of doing the longest procedure late (cardiac, 180 min x 0.5 = 90), so operating late always beats not operating.
**Revisit:** Weight sensitivity analysis once the evaluation harness (2.9) runs full days.
