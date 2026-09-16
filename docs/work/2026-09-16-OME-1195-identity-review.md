---
ticket: OME-1195
stack: aigateway
status: done
started: 2026-09-16
finished: 2026-09-16
---

# OME-1195 — Access identity review cleanup

## Intent

Owner approved correcting identity comments, adding an access-only identity regression, and annotating configured. Preserve current runtime behavior; do not conflate auth-mode/target changes with access-only changes.

## Planned changes

- core/model_parameter_contract.py: explicitly document freshness and route-added execution_access exclusions.
- routes/model_parameters.py: configured: bool annotation.
- Append test cases holding auth mode, account and target fixed across environment-access transitions.
- Update existing spec/plan/mirror and this ledger. No Linear comments.

## Test plan

- New regression protects already-correct behavior (no production bug to manufacture).
- Focused access tests; full Gateway gates including append-only; diff review.

## Acceptance

- Missing/configured/missing transitions preserve contract_id and context.revision with identity inputs held fixed.
- No prior tests modified and no runtime semantics changed.
- Push existing PR, leave unmerged.

## Outcome

- **Actual files:** identity comments, bool annotation, two appended environment-key variants, existing spec/plan/task mirror and this ledger.
- **Validation:** 13 access tests passed, including missing/configured/missing identity stability for both Gemini key variables. Full Gateway runner ALL GATES GREEN (append-only, lint, format, pyright, no-enterprise, full pytest/coverage); coverage 92.61% (80% floor). git diff --check passed.
- **Wisdom:** the real profileless-access selector runs while the independent auth-mode input is held fixed. Same authenticated account and anonymous target throughout. Both contract_id and context.revision plus parameter semantics remain equal. No production behavior changed, no prior tests edited, and no credentials/inference used.
- **Review:** independent review found no material issues and confirmed comment accuracy and test isolation.
- **Commit:** test(aigateway): pin access-independent contract identity (this ledger's commit); Refs: OME-1195.
- **Deviations:** no artificial RED for already-correct behavior; this is coverage/comment maintenance. No Linear comments. PR stays open and CI restarts on push.
