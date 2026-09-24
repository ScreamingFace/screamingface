---
ticket: OME-1222
stack: screamingface-engine
status: done
started: 2026-09-24
finished: 2026-09-24
---
# Document benchmark activity ownership

## Intent and plan
Owner requested author-facing logging guidance in both benchmark guides. Document the existing stage API, shared automatic observations, case-grading facts, explicit numbering and verification. No runtime changes, new issue, or Linear comments.

## Acceptance and verification
Check every API and responsibility against the stage-main source and existing tests. Preserve the existing guide structure. Markdown diff checks; no additional runtime tests for documentation-only changes.

## Outcome
Updated both guides. Checked stage enum, decorator, shared factory ownership, native case-execution terminal facts and Inspect scorer/async route against source. Verified referenced test paths and relative guide link. git diff --check passed. No runtime changes or additional test runs required. Existing full Engine gates remain applicable. No Linear comments.
