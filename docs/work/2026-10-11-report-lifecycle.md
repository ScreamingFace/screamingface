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

## Cross-process ownership and selection-time recovery follow-up

Intent: fix the two review reproductions on 7fe4dd65. Preserve every outstanding owner's lifecycle when notebooks share a results store, and track handled incomplete recovery even if all Candidate manifests fail selection.

Planned changes: new private ownership helper for coordinated POSIX read/merge/write and persisted operation/interrupt markers; retain legacy and best-effort behavior. Update lifecycle operation settlement and destination bootstrap. Enter recovery tracking before selecting a Candidate, resolving public evaluation IDs and saved keys through lightweight known membership. Preserve errors, cancellation, original-owner discovery and concurrent presentation. No dependencies, model calls or public API changes.

Test plan: real subprocesses with shared storage, recovery/export/display while another owner is alive, simultaneous operation settlement, original owner death followed by notebook notice, interruption clearing only after explicit recovery, legacy/corrupt/unwritable markers and symlinked locks. Sync/async all-corrupt recovery by evaluation ID settles handled failure ready and retains named errors; direct corrupt saved-key lookup preserves its metadata-invalid error and unfinished marker. Run all SDK gates and independent reviews before updating existing draft #1348. Existing tests append-only.

Outcome: both review findings fixed and verified for draft #1348. POSIX marker updates now lock the complete reread/merge/atomic-write operation and preserve all live foreign owners. Persisted interruptions remain discoverable until explicit recovery resolves them; discovery examines all recorded owners, including a dead evaluation alongside a live presentation. Older unfinished owner markers also survive unrelated presentation. Destination stores track their own work.

Recovery tracking now starts before Candidate selection. Sync/async all-corrupt evaluation recovery retains the existing candidates_failed error and named failures while settling ready. Direct corrupt saved-key lookup retains its existing result_metadata_invalid error and unfinished marker.

Added 14 append-only regression cases, with real subprocess owners and actual owner death. RED probes reproduced cross-process ownership replacement, stale cancellation resurrection, masked dead-owner discovery and older interrupted-marker loss before each correction. All 85 focused lifecycle/notice cases pass. Existing tests remain unchanged. Independent Standards and Spec reviews each have zero remaining actionable findings. Final stable-code SDK gates all pass: append-only tests, Ruff lint/format, Pyright, parallel full pytest (96.18% coverage), notebook checks, wheel/sdist build and distribution checks.

Wisdom/confidence: a private ownership helper coordinates the existing tracker without dependencies or public error/API changes. Optional metadata remains best-effort, symlinked locks are rejected, and liveness remains conservative outside POSIX or for inaccessible owners. Tests assert retained ownership, actual notice discovery and error/settlement behavior. No UI changes; existing screenshots remain applicable. No deviations from the requested fixes. Commit: fix(screamingface): preserve shared-store lifecycle ownership (OME-1572).


## Run-ID recovery alias follow-up

Intent: fix the review reproduction on 8e35fed2 where supported run-ID lookup bypasses source/destination lifecycle tracking.

Planned changes: resolve run-ID aliases through the existing store lookup only when lightweight evaluation-ID/saved-key membership has no match. Keep lightweight selection for corrupt candidates and preserve ambiguous/missing lookup errors. Register canonical evaluation paths before recovery selection/fetch. No public API or dependency changes.

Test plan: append sync/async success and cancellation regressions using outcome.run_id with separate destination stores; assert both markers are running during recovery and settle ready on success or remain unfinished on cancellation. Verify identical report JSON and interruption discovery. Preserve existing corrupt-selection, ambiguous/missing alias and concurrency tests. New tests fail first, then full SDK gates and parallel Standards/Spec review before updating draft #1348.

Outcome: reproduced the finding with four failing sync/async success/cancellation probes at 8e35fed2. The existing ResultStore.load unique-run lookup now resolves aliases only after lightweight membership finds no match, preserving evaluation-ID/saved-key corrupt-selection tracking. Missing/ambiguous aliases retain their existing errors and create no destination marker. No prior tests changed.

Added eight append-only regressions. Source and destination markers are running before fetch, settle ready on successful identical-JSON recovery, and remain running on cancellation; dead-owner classification retains the interruption. Missing/ambiguous aliases are covered in both APIs. All 93 focused lifecycle cases and 18 inherited saved-run tests pass (111 total). Independent Standards/Spec reviews have zero actionable findings; each reran focused tests. Final SDK gates all pass: append-only tests, Ruff lint/format, Pyright, parallel full pytest (96.18% coverage), notebook checks, build and distribution validation.

Wisdom/confidence: reuse the supported alias lookup instead of inventing another metadata resolver; preserve lightweight corrupt-selection precedence and public errors. Seven production lines in the private helper; no dependency, public API or UI changes. Existing screenshots remain applicable. No deviations. Commit: fix(screamingface): track recovery through run-ID aliases (OME-1572).


## 2026-10-12 merge-conflict resolution

Intent: merge current main into PR #1348 without dropping either branch's changes. The only conflict is concurrent feature entries in packages/screamingface/CHANGELOG.md: lifecycle recovery from this PR and multi-Attempt Benchmarks from main. Preserve both entries; retain all automatic merges. No new behavior or test changes.

Verification plan: inspect the resolved changelog and SDK README merge, check for unresolved hunks, and run all SDK gates on the combined tree before committing and pushing. Outcome: both changelog feature entries preserved, README automatic merge retained, and no unresolved hunks remain. All SDK gates pass against current main aab67fef: append-only tests, Ruff lint/format, Pyright, full parallel pytest with coverage floor, notebook checks, build and distribution checks. The fresh checkout required the existing notebook extra; no dependency or test changes. The test-preservation baseline is origin/main because its already-merged public API snapshot additions must be retained. No new SDK behavior or deviations. Merge commit: merge main into report lifecycle branch.
