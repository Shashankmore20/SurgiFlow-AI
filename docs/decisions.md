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