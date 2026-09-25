---
ticket: OME-1337
stack: screamingface-engine
status: in_progress
started: 2026-09-25
finished:
---

# Imported benchmark grading activity

## Intent
Make imported-board activity describe recording and actual scoring accurately, preserve judge case identity, and default structured activity to full. User approved implementation; retain Khoa ownership and leave no Linear comments.

## Planned changes
- Inspect single-shot recording and scorer observation; activity observer and vocabulary.
- Matching Client vocabulary/rendering only if needed for recording and explicit judge roles.
- Engine local/worker/Helm activity defaults and documentation.

## Test plan
- Reproduce full imported judged resolution with two cases and a fake judge.
- Assert recording precedes actual grading, case identity on judge events, and aggregation visibility.
- Verify explicit off remains respected and defaults are full across deployment paths.
- Run affected stack gates and preserve built-in benchmark semantics.

## Acceptance
No premature Graded events; judge identity is explicit; no private payloads in events; no paid calls; full default is consistent.

## Outcome
- Confirmed premature endpoint grading records in the complete two-case imported recipe.
- Fake-Gateway success, candidate failure, and judge failure all deliver aggregation;
  the reported six-minute stall was not reproduced.
- User approved migrating existing deployment assertions from off to full.
- User approved migrating the legacy imported-stage assertions; migration applied.
- Client notebook extra installed locally for gates; no dependency-file changes.
- Both producer and consumer receive closed recording/judge facts; existing four stage
  kinds remain unchanged. No URL4 SDK change, model prompt or score change.
- Owner paid notebook acceptance remains outstanding.


## Expanded audit and UI follow-up
- User requested limit=1 solo/fusion checks across all benchmarks, prioritizing
  Inspect Frontierscience, plus inline pagination beside Copy.
- FrontierScience: four real scorer/connector tests pass (olympic/research × solo/fusion)
  with simulated Gateway replies; no live-provider verification implied.
- Engine gates passed before expanded built-in audit. New audit reproduces missing
  judge case attribution in built-in rubric benchmarks; resolution remains in progress.
- Inline Older/Newer buttons replace the visible numeric page input; 23 focused
  pagination/panel/timeline tests pass. Notebook visual verification remains pending.
- Client run tests pass independently (14); full gates rerunning.

## Latest verification
- Exact Engine-owned grading request ownership now supplies built-in judge case IDs
  and role, isolated to the originating observation run. Ambiguous matches are not
  attributed; Candidate calls cannot borrow judge ownership. No protocol rewrite.
- Catalogue audit: 16 built-in + 46 deterministic imported + 4 FrontierScience
  format/recipe checks pass against real routes/scorers and simulated Gateway replies.
- Reproduced stranded starts under parallel completion bursts; admitted starts now
  prepay their terminal token. New regression and 52 existing activity tests pass.
- Client full suite: 1833 passed, 26 skipped, 3 failures from old fake ipywidgets module
  missing Button/Label. Approval requested for that test-double-only migration.
- Engine full gate rerunning after attribution and terminal reservation changes.
- Final focused audit: all 32 shipped boards covered (66 solo/fusion/format runs);
  additional burst tests cover completion, failure, and cancellation.
- Engine gate's first expanded run: 4241 passed, 9 skipped; sole failure was the
  new Inspect audit's directory placement. Moved it under the Inspect CI lane and
  extracted a shared test-only recipe harness; corrected focused checks pass.
- Rejected experimental query-parameter attribution after it changed nested recipe
  behavior. Removed it completely; generated benchmark expressions remain unchanged.
- Full Engine gates passed after the catalogue-audit placement fix.
- Extended terminal reservations to case-grading summaries after a separate red burst
  reproduction; 62 focused activity tests pass. Final Engine gates rerunning for that
  last extension. Client fixture approval and live notebook review remain pending.

## Final verification
- User approved the fake-ipywidgets Button/Label/on_click migration; existing assertions unchanged.
- Final Engine gates passed, including the case-summary terminal reservation changes.
- Notebook pagination visually verified: inline beside Copy, Older/Newer navigation, oldest-page boundary disabled. Synthetic 205-call preview; no paid provider calls.
- Full Client gates passed: lint, formatting, types, coverage, deterministic notebooks, build and distribution checks.
- Final review: generated benchmark expressions unchanged; run ownership and ambiguous attribution guarded; no live-provider success claimed. Ready for draft review.

## Pagination removal
User requested removing pagination entirely. Render all retained operations in the stable bounded-height scroll panel; retain Copy and history eviction notices. Migrate pagination assertions to full retained-line visibility and preserve transition/scroll-root checks.

Pagination removal outcome: 22 focused tests and full Client gates passed. Synthetic notebook confirms Copy remains and page controls are absent. Existing DRACO kernel left untouched.

## Timeline clarity
User approved completion-time ordering for summaries, inline call updates, explicit judge wording, hiding routine answer recording, and a verified evaluation completion footer. Test nested aggregation/judging, equal-time ordering, failure visibility and completion timestamps.

Timeline outcome: focused activity tests and full Client gates passed. Added nested judge/aggregation ordering, equal-timestamp concurrent completion, recording-failure visibility and verified-completion footer coverage. Renderer orders completion summaries by completion observation, retains call first-observation timestamps and updates calls inline.

## Sleek call wording
User approved Calling/Called and Grading with/Graded with, hiding the OpenRouter routing prefix visually while retaining full IDs in hover/copy. Graded with requires an explicit successful same-run, same-case grading summary. Preserve failures and copy timestamp separation.

Wording outcome: 102 focused activity checks and full Client gates passed. New tests pin routing-prefix display, full-ID metadata, active judge wording and same-case success requirement.
