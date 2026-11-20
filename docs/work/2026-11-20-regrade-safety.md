---
ticket: OME-1958
stack: screamingface
status: done
started: 2026-11-20
finished: 2026-11-20
---

# Regrade safety — preserve outcomes and constrain every replay

## Intent

Fix the six post-merge findings on #1926 before any production batch. The user authorized
steps 1 and 2 on 2026-11-20: merge #1993, implement and verify these fixes, then stop.
Deployment, production regrading and paid acceptance runs are outside this work.

## Planned changes

- SDK sync/async regrade: optional expected target, checked before replay and before posting.
- Batch: pass the declared target, validate success evidence, require source metadata.
- Journal: typed escaped keys, preserve valid final JSON, stable sidecar lock with inode
  checks, and idempotent retries of identical owner resolutions.
- Add regression tests; update incompatible prior fixtures only with owner permission.

## Test plan

Write failing tests for each reported scenario, then implement the fix. Include sync/async
target drift before replay and after replay, wrong returned evidence, real-process locking,
partial owner resolution recovery, and log compatibility. Run SDK and repository gates.

## Acceptance

No wrong-target score is posted; no unknown or unresolved entry is reported as settled;
interrupted execution remains resumable without concurrent replay. #1993 merged if CI permits.

## Outcome

Implemented all six fixes. The owner approved the prior-test updates; the public API snapshot
records only the two new optional arguments and is paired with a changelog entry. Initial RED
runs reproduced 33 failures. After integrating #1993, all 126 focused tests pass. Final SDK
gates pass (lint, formatting, types, full tests with the 95% coverage floor, JavaScript tests,
notebook checks, wheel build and distribution checks). Repository gates also pass.

An independent reviewer confirmed all six findings are resolved and independently passed
the 40 new regression cases available at review time. The operator docstring was corrected
after that review to explain valid-tail preservation and the persistent sidecar lock.

#1993 merged as `be06a6a05` on 2026-11-20. SDK and replay CI passed; the owner explicitly
authorized a normal merge despite GitHub installation-rate-limit failures in CodeQL and
preview cleanup. No admin bypass was used. This branch includes that merge.

No production deployment, regrade, browser login or paid model call was performed.
