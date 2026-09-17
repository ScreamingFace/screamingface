---
id: OME-903
linear_url: https://linear.app/openmined/issue/OME-903/add-the-full-healthbench-benchmark-all-525-cases-with-the-official
status: in_progress
type: feature
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-20
closed:
---

# Add the full HealthBench benchmark (all 525 cases) with the official score

Requested by Irina (2026-08-20). New benchmark identity serving all 525 HealthBench
Professional cases (assets already baked; worst30 is a serve-time filter), reusing the
existing candidate→judge pipeline, scored with the **official clipped mean**
(`max(0, mean)`) so results are comparable to published numbers.

Locked decisions (owner-approved 2026-08-20):

1. Dataset = the 525 already-baked `openai/healthbench-professional` rows — not the
   5,000-row main set, not the 1,000-row Hard split.
2. Score = official clipped mean; worst30 keeps its unclipped challenge metric.
3. Separate leaderboard: new benchmark id + revision; worst30 untouched.

Cost: a full run ≈ 3.3× worst30 per candidate; paid runs are owner-executed.
Scoreboard registration (seed entry) may split into a scoreboard sub-issue per the
cross-cutting rule.

Full body + sf-dark diagram: the Linear issue.

Owner decisions taken at implementation (2026-08-20): benchmark id
`healthbench-professional`; the mid-run check surface is advertised unchanged (same
criterion `healthbench-pass.v1`, same 0.5 threshold) so a corrective loop runs on either
board. Spec `docs/spec/2026-08-20-OME-903-healthbench-professional.md`, plan
`docs/plan/2026-08-20-OME-903-healthbench-professional.md`, ledger
`docs/work/2026-08-20-OME-903-healthbench-professional.md`.

Computed revision for the scoreboard seed (scoreboard sub-issue): `d8fb037307f35415`.

Scope extended by the owner (2026-08-20): the SDK example notebook ships in the same PR —
`08_healthbench_worst30.ipynb` becomes `08_healthbench.ipynb` and covers both boards.
`OME-905` was filed for that and canceled back into this issue.
