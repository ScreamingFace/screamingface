---
id: OME-1832
linear_url: https://linear.app/openmined/issue/OME-1832/remove-the-local-engines-version-skew-fallback-l7b-follow-up
status: in_review
type: task
priority: low
labels: [screamingface-engine, agentic, deferred]
parent: OME-1138
created: 2026-11-05
closed:
---

# Remove the Local Engine's version-skew fallback (L7b follow-up)

L7b (`OME-1830`) keeps a version-skew fallback for one release: against a gateway whose Connection
listing carries no `effective` field, the Local Engine selects the row labelled `screamingface`
and logs a notice once per process. This leaf removes it, so the Engine selects only by
`effective`. Deferred until an Engine release that carries L7b has shipped (owner decision 4 in
`docs/work/2026-11-04-effective-row-engine.md`). The `WHY` comment in
`apps/screamingface-engine/src/screamingface_engine/connections/aigateway_rows.py` names this
removal; spec `docs/spec/2026-10-29-local-engine-effective-row.md` §4.

- 2026-11-05: filed with L7b's PR.
- 2026-11-11: `screamingface-engine-v2.0.0` (L7b) and `aigateway-v1.0.0` (L7a) shipped; the PR
  opened. Not marked breaking (owner); the Local Engine now needs AI Gateway 1.0.0 or later. In
  Review.
