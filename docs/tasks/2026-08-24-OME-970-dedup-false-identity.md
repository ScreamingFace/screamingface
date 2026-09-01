---
id: OME-970
linear_url: https://linear.app/openmined/issue/OME-970/content-hash-dedup-hands-a-caller-another-runs-run-id
status: backlog
type: decision
priority: 3
labels: [scoreboard, agentic, design-session]
created: 2026-08-24
closed:
---

# Content-hash dedup hands a caller another run's run_id

Observed: two distinct runs with identical recipe and result collapse by content hash, and
the second caller receives 200 with the *first* run's `run_id` — so any trace context in
`metadata` names the wrong execution. Related: `Idempotency-Key` and `metadata.run_id` are
never cross-checked (the scoreboard source contains zero occurrences of `run_id`; the
coupling is a client convention). Dedup itself is defensible; asserting the wrong identity
back to the caller is not. Fix shape is an owner decision.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§4)
