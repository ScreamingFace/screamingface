---
ticket: OME-1197
stack: screamingface-engine
status: done
started: 2026-09-24
finished: 2026-09-24
---
# OME-1197 — Preserve explicit model-call failure origin

## Intent
Correct provider errors mislabeled as grading failures without guessing from rewritten error codes.

## Findings
URL4 ResolutionError has no origin/metadata field. Collection _error_payload only preserves kind, message, code and retryability. An Engine-only error attribute is lost. The existing three-case test constructs bare ResolutionError values and demands code-based classification, conflicting with this ticket's requirement that unmarked errors stay ambiguous.

## Planned changes / test plan / acceptance
Pending owner resolution of the ticket's explicit cross-package boundary and existing-test migration. Proposed optional generic origin field through URL4 collection; Engine connector stamps model_call, IFEval reads only that marker. Preserve protected checker failures, codes/messages, scores, and successful golden results. Add real connector tests for custom HTTP error codes, transport and malformed response failures.

## Outcome
Owner approved both boundary and test migration on 2026-09-24. No new ticket.

- Actual files: URL4 ResolutionError and collect serialization; Engine connector and IFEval classifier; three-case legacy test migration; new URL4 and Engine tests; README/changelogs and SDLC artifacts.
- RED: 11 URL4 and 8 Engine regression cases failed before implementation. GREEN: 12 URL4 cases (including real iteration with successful sibling), 30 focused Engine cases pass.
- Gates: URL4 ALL GATES GREEN; Engine ALL GATES GREEN (explicit --skip-append-only exception for the owner-approved legacy test migration). No other existing tests changed.
- Wisdom review: no new dependency or benchmark-specific import in URL4; origin omitted for legacy errors; codes/messages/retryability unchanged. Protected checker envelope wins. Successful expression generation untouched; no golden fixtures repinned. All ten connector ResolutionError constructions explicitly stamped. Other boards can consume the field separately, per ticket scope.
- Deviation: single cross-package PR under existing OME-1197 at owner's explicit request. The migrated bad-response test now follows the real connector's permanent=True instead of fabricating retryability.
- Commit: fix(engine): retain model-call origin through URL4 collection (see git history). Draft only; no merge, no Linear comments.
