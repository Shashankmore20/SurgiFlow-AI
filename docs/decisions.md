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
- Config keys `electives.procedure_mix` and `electives.cancellation_prob` come from `base.json`; the generator falls back to the same values (0.7/0.3, 0.05) if a config omits them..

**Why:** Separate streams keep each part of the day independent, so tuning one part doesn't change the others. Every method gets the same day (common random numbers). The "closer to target" rule never plans a room past regular hours (a room stops between 420 and 599 planned minutes), so overtime only comes from overruns and emergencies. Cancelling only before `planned_start` makes cancellations the same under every method; a later cancellation would depend on the policy and, since the objective doesn't score cancellations, would reward delaying electives. The deepcopy stops one run from leaking `start_time`, `arrival` and `hospital` into the next.

**Measured (base.json):** about 44 electives a day (Central 18.3, Riverside 13.8, Northside 12.0, over 100 seeds). Planned room totals are always 450 or 540 (cases are multiples of 90), 79% at 540; mean utilization 86.9%. First cases (minute 0) can't be cancelled, so about 1.7 cancellations a day (about 3.8% of all electives). Method comparisons come from the evaluation harness (D14) and are not recorded here, since they change whenever the config does.

**Alternatives:** Never exceed the target (rooms average well under 85%); keep adding until past the target (the plan itself would need overtime); one shared random stream (simpler, but any change reshuffles the whole day); cancellations after `planned_start` (more realistic, but needs a cancellation penalty in the objective first).

**Assumptions and sources:** The 85% target and the 70/30 mix are modelling assumptions; none of our reviewed papers gives values for them. The 5% cancellation rate is also an assumption (all causes, before the planned start); the only sourced figure we found is lower and narrower: about 1.1% of elective surgeries in England cancelled by hospitals for non-clinical reasons in 2019–20 (NHS England, cited in Gökalp, Gülpınar & Doan 2023, _EJOR_ 309, 832–844). The modelling choices are in line with the literature: lognormal surgery durations (Gökalp et al. 2023, citing May et al. 2000 and Strum et al. 1998, 2000; also Shehadeh & Padman 2022, _Computers & OR_ 137, 105523), planned duration equal to the procedure's average with the actual duration random and exponential gaps between emergency arrivals (Zhao et al. 2026, _IJPR_ 64(2), 719–750), and a 10-hour regular OR day (Gökalp et al. 2023). Overtime and idle time are both costly (Shehadeh & Padman 2022; Zhao et al. 2026), which is why rooms are filled to about 85% rather than 100%. All numbers are in the config so they can be varied.

**Revisit:** Run 1.1% as a sensitivity case (team decision: 5% is the base; as a new config file, since configs that have produced results are not edited); if we find sourced figures for utilization or case mix; if the simulator starts using `planned_room`; when SA/GA replace the default plan (disruption is then measured against their plan); late cancellations if the objective adds a cancellation cost; cancellations caused by bed or capacity shortage (reported as a real cause in Shehadeh & Padman 2022 and Gökalp et al. 2023; ours are random).

## D12 — Durations, emergencies/cancellations and the bed layer (tasks 2.3–2.5)

**Decision:**

- Actual duration is lognormal around the planned duration (`sample_actual_duration`, sigma 0.25). The mu shift keeps the average equal to the planned length, so some cases overrun and some finish early. Minimum 1 minute. Policies only see `duration` (planned).
- Emergencies arrive as a Poisson process (`arrivals_per_day`). Urgency is drawn from `urgency_levels`, the procedure from `emergencies.procedure_mix` (uniform if the key is missing), and the zone uniformly.
- Bed layer: after surgery a patient needs an ICU/recovery bed with probability `icu_prob` per procedure. The stay is lognormal (sigma 0.3) around `icu_stay_min` (default 480). A room stays blocked until a bed frees up (`blocked_min`).
- All draws happen in the generator, so every method sees the same patients (D9).
- Config keys: duration_sigma (0.25), bed_stay_sigma (0.3), procedures.*.icu_stay_min (480), emergencies.procedure_mix (general 0.5 / trauma 0.3 / cardiac 0.2), electives.procedure_mix, electives.cancellation_prob. Code keeps these values as defaults. priority removed; urgency (1 = critical) is the only urgency field.

**Why:** Lognormal is the standard model for surgery durations (Gökalp et al. 2023, citing May et al. 2000 and Strum et al. 1998, 2000; Shehadeh & Padman 2022). A 10-hour regular OR day (600 min) matches Gökalp et al. 2023. Downstream beds limit OR throughput (Shehadeh & Padman 2022).

**Assumptions:** sigma values, the 480-min default stay and the emergency procedure mix are modelling choices, not sourced.

**Revisit:** Fit sigma per procedure if we find data. Add `icu_stay_min` per procedure to base.json.

## D13 — Demo viewer (2.10 / 5.5)

**Decision:** An animated, interactive replay of one simulated day built with matplotlib (`src/surgiflow/viz/`, run with `scripts/demo.py`): Gantt chart of every OR, a map with ambulances moving from zone to hospital, and live bars for ORs busy, patients waiting and beds in use. Play/pause, speed and a time slider; exports to GIF/MP4 for slides.
**How it works:** The simulation runs first; the viewer only replays its log (`Timeline.state_at(t)`), so it can't affect results. `timeline.py` has no plotting code and is tested in CI. The demo uses the same days and methods as the harness, so it always shows what was measured.
**Why matplotlib, not pygame:** Already installed, the same drawing code gives static report figures and video exports, and it can be tested headless.
**Note:** Map positions are for display only; travel times still come from `travel_time_min`.

## D14 — Evaluation harness (2.9)

**Decision:** `evaluation/harness.py` + `scripts/evaluate.py` run every method on the same seeded days from the generator (default 50) and report, per method: mean cost, 95% confidence interval, per-patient cost and each component; plus a head-to-head count against a reference method (better / worse / tied on the same day). Results go to a new `results/eval_<timestamp>/` folder with the config, seeds, methods and git commit.
**Fresh state per run:** every (method, day) gets a new `Network`, new patients (`load_instance` deep-copies) and a new `Setup`. Reusing a Network took seed 1 from cost 1261 to 47,916 (Emmanuel's check), because rooms busy at minute 1440 were never freed.
**Adding methods (2.8, SA, GA, RL):** a top-level `build(cfg) -> Setup` in `evaluation/methods.py`. `Setup.before_run` lets SA/GA replace the elective plan before the day starts.
**Why paired comparison:** methods face identical days, so "better on 155/200 days" removes day-to-day luck that averages alone hide.
**Why standard library only:** CI installs only pytest.
**First result (200 days, base.json):** urgency-first + nearest beat FIFO + nearest on 155 days, tied 45, lost 0; mean cost 1124 vs 1657, mostly by cutting minutes past the safe-wait limit (4 vs 29) at the price of more elective disruption (1478 vs 1269).

## D15 — Capacity-aware allocation baseline (task 2.8)

**Decision:** `capacity_aware_policy(patient, network, clock)` in `agents/baselines.py`. For every hospital that can do the procedure it estimates the minutes from the call to the start of surgery, and sends the patient to the smallest. Arrival = now + travel time. Each room is expected to free at `start_time + duration` (planned; an overrunning surgery counts as free now). Everyone already waiting or inbound is assumed to go first, each taking the earliest free room (greedy list scheduling); the patient then starts at the later of their arrival and the earliest free room. Ties go to the nearer hospital, then the lower id. Raises if no hospital is capable. Registered in the harness as `fifo+capacity` and `urgency+capacity`. The nearest-hospital baseline already exists (`nearest_capable_policy`).

**Why:** An emergency's wait is measured from the call and includes travel (D9), so this estimates exactly what the objective scores. Nearest-capable ignores queues. Counting `inbound` stops several calls in a row from all being sent to the same "empty" hospital. Assuming everyone is ahead makes no assumption about the scheduling policy it is paired with, and never underestimates the wait.

**Limits:** Uses planned durations only, so estimates are wrong when surgeries overrun. Ignores recovery beds (a room blocked waiting for a bed looks free), booked electives that have not arrived yet, and future calls. Under urgency-first it overestimates the wait of urgent patients, who would jump the queue. With the current emergency mix, half the calls are trauma and can only go to Central, so there is a choice for only about half.

**Result (200 days, base.json, harness D14):** vs nearest with the same scheduler, mean cost 1507 vs 1745 under FIFO (better on 96 days, worse on 28, tied 76) and 1093 vs 1138 under urgency-first (better on 80, worse on 43, tied 77). A modest gain; under urgency-first the difference in means is within the 95% intervals. Scheduling matters more than allocation here (urgency-first vs FIFO: 1138 vs 1745).

**Alternatives:** Count only patients at least as urgent as ahead (accurate with urgency-first, too optimistic with FIFO); least-loaded hospital ignoring travel; a hard rule preferring hospitals that meet `max_wait` (minimizing the estimate already favours them).

**Revisit:** Urgency-aware queue estimate; include bed availability; if the emergency procedure mix changes; RL allocation (4.x) should beat this.

## D16 — Urgency-first scheduling baseline (task 2.7)

**Decision:** `urgency_first_policy(hospital, clock)` in `agents/baselines.py`. When a room is free it picks the waiting patient with the smallest `(urgency, arrival, id)`: lower urgency number first (1 critical, 2 urgent, 3 semi-urgent), electives (urgency `None`) after every emergency, ties to the earlier arrival, then the lower id. It never returns `None` while someone is waiting, reads only `urgency`, `arrival` and `id`, and does not modify `hospital.waiting`. FCFS already exists as `fifo_policy` in `core.py`. Uses `urgency`, not the legacy `priority` field. Written after the fact; merged in PR #58.

**Why:** The objective weights emergency waits by urgency and charges 10 per minute past `max_wait` (D8), so serving the most urgent first is the simplest rule aimed at the largest costs, and it is what a human scheduler would do by default. The id as the last tie-break makes the choice deterministic, so runs are reproducible (D9). Never idling a room keeps it a plain dispatching rule that is easy to compare against.

**Limits:** Electives can starve if emergencies keep arriving. Non-preemptive (a surgery in progress is never interrupted). Ignores `max_wait`, durations, overtime and what is about to arrive.

**Result (200 days, base.json, harness D14):** vs FIFO with nearest-hospital allocation, mean cost 1138 vs 1745; better on 156 days, worse on 3, tied 41. Minutes past the safe-wait limit drop from 35 to 4, at the price of more elective disruption (1431 vs 1218).

**Alternatives:** Earliest deadline first (`call_time + max_wait`); shortest planned duration first; urgency with aging so electives cannot starve; holding a room free for expected emergencies.

**Revisit:** Add an earliest-deadline baseline if the team wants a third; aging if elective starvation shows up in results; SA/GA and RL scheduling (3.x, 4.x) should beat this.
