---
id: OME-1094
linear_url: https://linear.app/openmined/issue/OME-1094/pin-each-failed-cases-failure-code-in-the-e2e-goldens-so-a
status: in_progress
type:
priority: high
labels:
  - py-screamingface
  - agentic
  - autonomous
created: 2026-09-03
closed:
---

# Pin each failed case's failure code in the e2e goldens so a reclassification can't pass as "failed"

The e2e replay golden pins each case's status word only. Five different failure
reasons all spell `failed`, so a refactor that swaps one reason for another keeps CI
green. This unit adds a per-case failure map (stage + code) to the golden, a new
"codes" rung between statuses and coverage in the compare ladder, a validator that
refuses a scored case with a failure entry or a failed case without one, and a
fixtures-sourced re-bless mode that refuses to write when the replayed score,
statuses, or expression differ from the committed golden.

Gate for `OME-1039` (blocks relation), the first extraction PR of the `OME-1024` spine.

Ledger: `docs/work/2026-09-03-OME-1094-golden-failure-codes.md`.
