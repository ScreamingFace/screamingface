---
id: OME-1881
linear_url: https://linear.app/openmined/issue/OME-1881/size-the-evaluate-fan-out-from-the-engines-per-caller-cap
status: in_progress
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1314
created: 2026-11-11
closed:
---

# Size the evaluate fan-out from the Engine's per-caller cap

`sf.evaluate` sent at most 8 Candidate runs at once, a fixed value. The Client now reads
`GET /v1/limits` once per multi-Candidate evaluation and sends `min(Candidates, cap)` at once. It
uses 8 when the Engine gives no value, so it is safe against every Engine version.

- 2026-11-11: filed under epic `OME-1314` (E23) at PR-open. Engine half: `OME-1880`.
- Spec: `docs/spec/2026-11-10-per-user-parallel-runs.md` (D3), added by the `OME-1880` PR.
- 2026-11-12: PR #1745 review (khoaguin, non-blocking): each fallback of the cap read now logs its
  cause at DEBUG (status code or error type, never the body). Two concurrent `evaluate()` calls by
  one caller each send up to the cap: recorded as watch-list W8 in the spec (no change now).
