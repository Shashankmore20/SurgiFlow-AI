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
- `Surgery.start_time` and `Hospital.inbound` are readable by policies and the allocator (read-only, like all simulator state). A cancelled patient's CALL and ARRIVAL events are dropped, so they never enter a queue.
- Every log record has the fields in `interfaces.LOG_FIELDS`, which the objective reads.
  **Rules:** policies never read `actual_duration`; policies never modify the network; an emergency's wait is measured from `call_time` (includes travel); an elective's `arrival` is its `planned_start`.
  **Update:** names aligned with Zaiba's 2.3–2.5 work (`actual_duration`, `needs_bed`, `call_time`) when merging PR #52.
  **Why:** Lets generator, simulator and policies be built and tested in parallel; the same seed gives every method identical inputs.
  **Alternatives:** Randomness inside the simulator (methods would face different days; harder to test).
  **Revisit:** Add the transfer hook in 2.11.

## D10 — Overtime and unserved patients in the objective

**Decision:**

- Overtime counts only surgeries that _started_ during regular hours (before `regular_hours_min`) and ran past it, measured until the room is actually free (`room_release`, so bed-blocking counts). Surgeries started after regular hours are on-call work and don't count.
- Patients who never get surgery (`sim.unserved()`: still waiting or still travelling when the run stops) are scored: emergencies keep accumulating wait and delay until `horizon_min`; electives count as disrupted until `horizon_min`. Every unserved patient also costs a flat 200 (`weights.unserved`).
- The objective also reports `patients` (served + unserved), not weighted, for per-patient averages. Raw totals are only compared within the same config.
  **Why:** In a test day (seed 1, emergencies only), night emergencies made overtime 78% of the cost (1733 of 1110 total); with the fix it is 135 of 311. Without the unserved penalty, a policy that never operates would score zero disruption and zero overtime.
  **Choosing 200:** more than the overtime cost of doing the longest procedure late (cardiac, 180 min x 0.5 = 90), so operating late always beats not operating.
  **Revisit:** Weight sensitivity analysis once the evaluation harness (2.9) runs full days.

## D11 — Elective generation and the instance generator (task 2.6)

**Decision:**

- `generate(config, seed) -> Instance` and `load_instance(sim, instance)` in `sim/generator.py`. All randomness for a day happens here; the simulator stays deterministic (D9).
- Three random streams per seed: `seed*1000+1` electives, `+2` emergencies, `+3` cancellations. Emergencies reuse `generate_emergencies`; electives reuse `sample_actual_duration` and `sample_bed_need`.
- Electives are the hospital's default plan. Every room is filled back to back from minute 0. Each case is general (0.7) or cardiac (0.3), never trauma, and only procedures the hospital can do (Northside: general only). Planned duration = the procedure's `mean_duration_min`; `actual_duration` is hidden. A case is added only if it brings the room's planned total closer to the target (`target_utilization` × `regular_hours_min` = 510); otherwise the room is full. `arrival = planned_start`. Ids are `H{hospital}-R{room}-{k}` (unique, never clashing with emergency ids `E0, E1, ...`).
- Cancellations: each elective with `planned_start > 0` is cancelled with probability `cancellation_prob` (0.05), at a uniform minute in `[0, planned_start)`. Every elective uses exactly two draws, so changing the probability never moves anyone's cancel time. Stored in `Instance.cancellations` as `(surgery_id, minute)`.
- `load_instance` deep-copies the instance and loads electives, emergencies, then cancellations (matched to the copies by id), in that fixed order. Each run also needs a fresh `Network`, since the simulator writes into hospitals too.
- Config keys `electives.procedure_mix` and `electives.cancellation_prob` are read with the values above as fallbacks until they are in `base.json`.

**Why:** Separate streams keep each part of the day independent, so tuning one part doesn't change the others. Every method gets the same day (common random numbers). The "closer to target" rule never plans a room past regular hours (a room stops between 420 and 599 planned minutes), so overtime only comes from overruns and emergencies. Cancelling only before `planned_start` makes cancellations the same under every method; a later cancellation would depend on the policy and, since the objective doesn't score cancellations, would reward delaying electives. The deepcopy stops one run from leaking `start_time`, `arrival` and `hospital` into the next.

**Measured (base.json):** about 44 electives a day (Central 18.3, Riverside 13.8, Northside 12.0, over 100 seeds). Planned room totals are always 450 or 540 (cases are multiples of 90), 79% at 540; mean utilization 86.9%. First cases (minute 0) can't be cancelled, so about 1.7 cancellations a day (about 3.8% of all electives). On seeds 1–10, urgency-first beat FIFO on 8 days and tied on 2 (mean cost 946 vs 1324); a sanity check, not a reported result.

**Alternatives:** Never exceed the target (rooms average well under 85%); keep adding until past the target (the plan itself would need overtime); one shared random stream (simpler, but any change reshuffles the whole day); cancellations after `planned_start` (more realistic, but needs a cancellation penalty in the objective first).

**Assumptions and sources:** The 85% target and the 70/30 mix are modelling assumptions; none of our reviewed papers gives values for them. The 5% cancellation rate is also an assumption (all causes, before the planned start); the only sourced figure we found is lower and narrower: about 1.1% of elective surgeries in England cancelled by hospitals for non-clinical reasons in 2019–20 (NHS England, cited in Gökalp, Gülpınar & Doan 2023, _EJOR_ 309, 832–844). The modelling choices are in line with the literature: lognormal surgery durations (Gökalp et al. 2023, citing May et al. 2000 and Strum et al. 1998, 2000; also Shehadeh & Padman 2022, _Computers & OR_ 137, 105523), planned duration equal to the procedure's average with the actual duration random and exponential gaps between emergency arrivals (Zhao et al. 2026, _IJPR_ 64(2), 719–750), and a 10-hour regular OR day (Gökalp et al. 2023). Overtime and idle time are both costly (Shehadeh & Padman 2022; Zhao et al. 2026), which is why rooms are filled to about 85% rather than 100%. All numbers are in the config so they can be varied.

**Revisit:** Whether to use 1.1% (or run it as a sensitivity case) once the team decides; if we find sourced figures for utilization or case mix; if the simulator starts using `planned_room`; when SA/GA replace the default plan (disruption is then measured against their plan); late cancellations if the objective adds a cancellation cost; cancellations caused by bed or capacity shortage (reported as a real cause in Shehadeh & Padman 2022 and Gökalp et al. 2023; ours are random).
