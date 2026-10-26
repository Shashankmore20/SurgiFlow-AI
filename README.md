## Setup

We use the course conda environment (Python 3.14).

```bash
conda create -n FAI python=3.14 -c conda-forge   # skip if you already have it
conda activate FAI
pip install -r requirements.txt
```

## Repository structure

```
configs/               simulation parameters (hospitals, ORs, beds, arrival rates)
src/surgiflow/sim/     simulator: hospitals, patients, events, environment
src/surgiflow/agents/  baselines, search (SA/GA), RL (Q-learning/SARSA)
src/surgiflow/evaluation/  metrics and plots
scripts/               entry points: experiments, training, cluster jobs
tests/                 tests
report/                LaTeX writeup
results/               experiment outputs (not committed)
```

## Workflow

- Never push to `main`; work on your branch and open a PR.
- Sync with main at the start of every session: `git fetch origin && git merge origin/main`.
- Put `Closes #N` in the PR description to close the issue.
- Merge with "Create a merge commit" (not squash).