---
ticket: OME-1197
stack: screamingface-engine
status: done
started: 2026-09-24
finished: 2026-09-24
---
# OME-1197 — Use the existing collected error kind

## Intent
Replace the proposed URL4 origin extension with Engine-owned candidate boundary attribution, approved by the owner after spec/SDK review.

## Planned changes
Remove the draft's URL4 changes and connector stamps. Introduce CandidateExecutionError at the candidate adapter's execution boundary; IFEval consumes the existing kind field. Revise draft-specific origin tests and migrate provider tests through the actual candidate boundary, preserving diagnostic assertions. Update spec, plan and PR description.

## Test plan
RED real candidate execution plus collection with rewritten HTTP codes; legacy codes outside candidate remain unclassified; protected grading wins; successful sibling retained. Verify refusal/policy contracts and run full Engine gates plus guarded IFEval replay.

## Acceptance
No URL4 package changes; correct candidate/grading classification with unchanged error code, message and retryability. Draft only, no merge or new issue.

## Outcome
Implemented the Engine-only boundary and removed all draft URL4 changes plus connector stamps. Updated regressions retain diagnostics and exercise actual candidate execution plus collection. 76 focused tests passed, full Engine gates ALL GATES GREEN (owner-approved test migration, --skip-append-only), and real IFEval replay passed with score 0.9184 unchanged. Broader board replay is being checked before PR update. git diff --check passed.

Wisdom: reuse existing error.kind rather than extend the protocol; core owns the exception and the world adapter raises it, with no plugin imports. Catch only Url4Error during recipe execution, preserving validation/refusal behavior and leaving cancellation/programming exceptions alone. No grammar, dependency, prompt or successful result changes.

Deviation: removed draft-specific URL4 tests with the rejected extension, replacing domain coverage in Engine. Updated the earlier provider tests to cross the candidate boundary as authorized. The new sibling test required weighted source bindings and a passthrough test processor to represent the Engine recipe correctly; the first gate run caught this test setup error. Final gates passed. Commit: fix(engine): attribute failures at candidate execution boundary.
