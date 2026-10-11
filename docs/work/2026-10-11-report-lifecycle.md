---
ticket: OME-1572
stack: screamingface
status: in_progress
started: 2026-10-11
finished:
---

# Report lifecycle — discover interrupted saved results

## Intent

Extract the final SDK slice from #1156 onto current main after #1241, #1269, #1345 and #1347 merged. When a notebook process dies during evaluation, report rendering or export, reopening the SDK should identify completed saved results and show recovery guidance without rerunning models.

## Planned changes

- Add private lifecycle markers and interrupted-owner discovery using existing saved evaluation manifests.
- Wire lifecycle transitions into result preparation/settlement, explicit recovery, report display and streaming export; keep concurrent operations correctly marked.
- Show the existing shared notebook info notice on persisted Client startup, once per evaluation/Engine/store, with an explicit sf.reports.get command.
- Preserve current main's transport defaults, partial-report contracts, corrupt-sibling protections, Colab fixes and accounting data.
- Add only new regression tests, spec/plan, README guidance and before/after notice screenshots. Create the leaf ticket under OME-1294 at draft PR publication.

## Test plan

New tests first: healthy/headless/legacy silence; dead and inaccessible owners; active/export/render markers; concurrent/nested operation settlement; complete/partial/no-decode recovery; sync/async cancellation; optional corrupt/unwritable marker failures; safe paths; actual dead subprocess discovery. Run every SDK gate and independent Standards/Spec reviews. Verify the actual notice rendering in light/dark and capture before/after screenshots with synthetic saved results. No paid calls.

## Acceptance

Interrupted saved results are discoverable in a notebook without startup model calls, while healthy/active/legacy reports stay quiet. Handled results settle ready; interrupted operations retain unfinished markers. Optional metadata or display failure never discards usable results. Existing tests remain unchanged, required gates pass, and a focused draft PR is published without merging.

## Outcome

Implementation complete; all SDK gates pass, draft prepared for owner review.

- Added 48 regression cases. Initial new tests were red before implementation; all 48 now pass. Existing tests are unchanged.
- Standards review: 0 remaining findings. Spec review: 0 remaining findings after fixing simultaneous recovery, interrupted export/presentation, cancelled recovery overlapping an unrelated successful export, and marker symlink confinement.
- An actual exited subprocess owns the retained synthetic fixture. Baseline main Client emits no notice; this branch emits one shared info notice, suppresses a second startup notice, and explicitly recovers identical full report JSON without model calls.
- Actual startup notice HTML captured in a labeled notebook fixture in light/dark, visually inspected; screenshots: docs/screenshots/2026-10-11-report-lifecycle/. This checks the shared renderer, not a new live Colab runtime session.
- Full SDK gates: append-only test check, Ruff lint/format, Pyright, parallel full pytest with 96% coverage, notebook smoke checks, wheel/sdist build and distribution checks all pass.
- No dependencies or Engine changes. Recovery guidance is conservative on non-POSIX/inaccessible owners; PID reuse can suppress it. Completion records and available artifacts are still required, as documented.
- Draft is the fifth/final SDK extraction from #1156. Separate Engine/runtime artifact persistence #1217 is outside this slice.

## Active evaluation follow-up

User requested updating draft #1348 after review reproduced recovery, export and display settling the marker ready inside an open prepared evaluation. Register the entire prepared evaluation scope in the existing operation tracker. Preserve settlement only for success or candidates_failed, unfinished cancellation/unexpected errors, and unconditional transport membership cleanup.

Planned files: runner.py, private lifecycle tracker, new append-only active-evaluation tests, corresponding plan/spec evidence and this ledger. Test plan: the three production operations remain running inside the prepared scope; success/handled failures settle ready, other failures remain unfinished; transport cleanup always occurs; surviving presentation operations remain pending. New tests must fail first. Rerun all SDK gates and independent review; update the same draft without comments or merging.

Outcome: fixed and verified for the existing draft PR #1348. The prepared evaluation now stays registered throughout execution. Only candidates_failed is treated as a handled evaluation error; transport cleanup still runs for every exit. Explicit recovery alone clears prior interruptions, so successful evaluation cannot hide cancelled Candidate recovery/export/display.

Added 23 append-only regression cases: 20 initially failed for unregistered evaluation scope, then 3 additionally failed for interruption clearing at evaluation completion. All 71 lifecycle/notice cases now pass. Standards and Spec reviews each have zero remaining findings. Final full SDK gates all pass, with 96.18% coverage, notebook checks and wheel/sdist distribution verification. Prior tests remain unchanged. No UI changes; prior screenshots remain applicable.

Wisdom/confidence: reuse the existing tracker rather than a second registry; preserve exact handled-error classification and keep explicit recovery's interruption resolution separate from ordinary settlement. Private lifecycle helpers only; no public API, schema, dependency, authentication or model-call changes. No deviations from the requested fix.
