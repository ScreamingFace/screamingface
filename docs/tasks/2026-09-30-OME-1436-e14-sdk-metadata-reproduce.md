---
id: OME-1436
linear_url: https://linear.app/openmined/issue/OME-1436/add-e14-metadata-capturetrue-and-sfreproduce-to-the-sdk
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
created: 2026-09-30
closed:
---

# Add E14 metadata, capture=True and sf.reproduce to the SDK

Parent: OME-1307. 2 PRs, in the E14 stack.

Ledger (A2): `docs/work/2026-10-06-e14-a2-sdk-metadata.md`.
Ledger (B5): `docs/work/2026-10-06-e14-b5-sdk-reproduce.md`.
Spec: `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` (binding).

Scope:

- A2: `submit(..., paper_url=)`, `sf.leaderboards.edit(...)` and `sf.leaderboards.metadata_events(...)`, in sync and async form.
- B5: `evaluate(..., capture=True)` on every entry point. A warning shows when the Engine did not capture.
- B5: `sf.reproduce(score, *, record=True)` returns `exact`, `failed` or `not_reproducible`. An exact replay is recorded on the score.

- 2026-10-09: PR opened on branch `OME-1436-e14-a2-sdk-metadata`; gates green against the branch below; owner-approved test edits recorded in the ledger.
- 2026-10-09: PR opened on branch `OME-1436-e14-b5-sdk-reproduce`; gates green against the branch below; owner-approved test edits recorded in the ledger.
