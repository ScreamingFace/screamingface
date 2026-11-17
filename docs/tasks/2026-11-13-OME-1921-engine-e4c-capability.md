---
id: OME-1921
linear_url: https://linear.app/openmined/issue/OME-1921/tell-clients-that-the-engine-supports-e4c-branches
status: backlog
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-11-13
closed:
---

# Tell clients that the Engine supports E4c branches

Mirror of OME-1921 (parent epic OME-1291, E4c).

A follow-up of the PR #1733 review (sergio-bershadsky, S1, round 3). Not part of #1733.

**Problem.** A new SDK on an Engine without E4c sends a Gate recipe. The Engine runs and pays every member first, then fails each Case on `phase=decide`. Today the only protection is the release order (the Engine ships first, spec `00-overview.md` §8). Nothing in the code refuses this.

**This issue (Engine side).** The Engine tells a client that it supports E4c branches (Gate, Cascade, budget), for example a capability field in `GET /v1/operators` or in the Engine info. The SDK side is a separate issue that is blocked by this one.

**Done when.** A client can read the E4c capability before it submits a run. A contract test pins the field.

Ledger: `docs/work/2026-10-22-e4c-routers-cascades.md` (2026-11-13 review round 3).
