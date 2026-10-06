---
id: OME-1502
linear_url: https://linear.app/openmined/issue/OME-1502/point-the-clients-default-engine-and-leaderboard-at-prod
status: in_progress
type: task
priority: 2
labels: [client-sf, agentic, autonomous]
created: 2026-10-06
closed:
---

# Point the Client's default engine and leaderboard at prod

Parent epic: OME-1304 (E11 · Production release) — names this deliverable: "Requires also
pinning client to prod instead of *.dev.*".

Flip the `screamingface` Client's shipped defaults from the dev hosts to the live prod hosts:
`DEFAULT_ENGINE_URL` → `https://fusion.screamingface.ai`, `DEFAULT_SCOREBOARD_URL` →
`https://leaderboard.screamingface.ai`. Env overrides (`SCREAMINGFACE_ENGINE_URL` /
`SCREAMINGFACE_SCOREBOARD_URL`) still win. Minimal scope (user-confirmed): the two defaults +
the tests/snapshot that assert them; docs/examples/e2e/fixtures left on dev.

Spec: docs/spec/2026-10-06-client-prod-default-endpoints.md
Plan: docs/plan/2026-10-06-client-prod-default-endpoints.md
Ledger: docs/work/2026-10-06-client-prod-default-endpoints.md
