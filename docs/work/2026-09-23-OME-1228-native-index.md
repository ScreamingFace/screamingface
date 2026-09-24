---
ticket: OME-1228
stack: screamingface-engine
status: in_progress
started: 2026-09-23
finished:
---

# Native iteration index integration

## Intent

Update #988 after #1039 merged; eliminate synthetic row-position fields and the extra
selected-cases endpoint. Then restack #980 and verify Client activity behavior.

## Planned changes

Use native `$index`, native slicing and the selected count already known at protocol build
time. Decode a zero-based index into the existing one-based activity position. Preserve
case IDs, model input bytes, grading and accounting. The removed selector also validates
collection shape and minimum length before candidate execution; proposed placement is the
existing cases handler, approved by the owner. No additional selection route.

## Test plan

RED/GREEN native-index transport tests; cases loader validation before any model calls;
all shipped board builders including Inspect and structured MedXpert; unchanged replay
outcomes with expression-only fingerprint migration (owner approved).
Full Engine and Client gates, then stage-event stack checks and notebook smoke.

## Acceptance

No selected-cases route or synthetic row fields; correct one-based position and selected
total; invalid collections rejected before inference; unchanged scores and prompts.

## Outcome

- Rebased #988 onto origin/main including native `$index` without conflicts.
- Replaced selector registration and synthetic row fields with native slicing/indexing.
  Existing cases handlers validate selected shape/count before inference. All shipped
  installers use the shared validator, including Inspect, rubric boards and spine boards.
- Converted candidate envelope case_index to the unchanged one-based activity position.
- Seven new regression tests pass. Migrated old selector tests with explicit owner approval;
  preserved ordering, malformed-data, preflight, privacy and model-input assertions.
- Full Engine gates pass: lint, format, types, layering, complete tests and coverage.
  Inspect extra installed. Approved append-only exception covers obsolete tests/snapshots.
- Independent spec and standards reviews found no remaining issues after missing legacy
  loader registrations were fixed and their route coverage added.
- Four cached replays (382 cases) preserve scores, statuses, failures and coverage. The
  separate OME-1229 fixture commit changes only expression hashes.
- Wisdom: no new endpoint, SDK capability, dependency or telemetry shape. Documented cases
  processor/count-intent contract replaces bare data reads; no compatibility route added.
- Delivery: push #988, restack #980, then run preview checks; no merge requested.
