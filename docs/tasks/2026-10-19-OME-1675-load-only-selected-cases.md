---
id: OME-1675
linear_url: https://linear.app/openmined/issue/OME-1675/load-only-the-selected-cases-in-imported-board-runs
status: backlog
type: task
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-10-19
closed:
---

# Load only the selected cases in imported-board runs

Every run of an imported board loads the board's whole `cases.json`, whatever its `limit`. For
ContractEval (192 MiB, 4,182 full CUAD contracts, each contract 41 times) that is a fixed cost
of more than 1 GiB per run: a 3-case run peaked at 1,828–1,870 MiB in kind before its first
model call. OME-1648 raised the per-run budget to 2.5 GiB to unblock it.

Scope: slice the selected cases before parse and serialize; store each shared contract once in
the bundle (candidate call bytes unchanged, so the cache still hits); measure `inspect-bbq` and
`inspect-worldsense`; then lower the per-run budget again (owner approval for the floor test).

- 2026-10-19: filed at OME-1648's PR-open, under epic OME-1314, related to OME-1648.
