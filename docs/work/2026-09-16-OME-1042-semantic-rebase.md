---
ticket: OME-1042
stack: screamingface
status: done
started: 2026-09-16
finished: 2026-09-16
---

# OME-1042 — Access and answer-seed preflight integration

## Intent

Owner approved semantic rebase of PR933 and explicit None handling for prefetched details. Preserve access checks for every model, seed validation before spend, and admission-response reuse. Shared test-helper extraction remains separate.

## Planned changes

- Resolve preflight/runner conflicts and changelog; prefetched becomes keyword-only alongside answer_seed.
- Fetch all candidate models once; validate access, explicit parameters and seed from same documents.
- Add combined regression coverage; retain existing assertions.

## Test plan

- Access matrix plus answer-seed, parameter and admission tests together.
- Full Client gates including coverage, notebooks, build and distribution checks.

## Acceptance

- Both preflight guarantees preserved in sync/async; admission documents reused.
- Push existing PR with explicit lease, leave unmerged. No Linear comments.

## Outcome

- **Rebase:** onto `0c0abfcf`; resolved two source conflicts and changelog while retaining both feature intents. Rebased commits `99a01a80` and `355f86c6`.
- **Actual files:** preflight and runner integration, changelog, eight appended combined access/seed tests, spec/plan/mirror and this ledger. No shared fixture extraction.
- **Validation:** 83 existing access/parameter/admission/seed/replay-discovery tests passed together; 91 passed after adding eight combined sync/async, listed/admission, missing/configured cases. Each new case checks one details fetch, expected access/seed error, no dispatch and no observer events.
- **Full gates:** ALL GATES GREEN: append-only against HEAD, lint, format, pyright, full tests with 95.23% coverage (95% floor), notebook generation checks, build, distribution verification. git diff --check passed.
- **Wisdom:** selected Candidates retain answer_seed for preflight/observers/dispatch/results. All required models have access validated; prefetched documents remain reused; explicit None replaces truthiness. Independent integration review found no material regressions.
- **Commit:** test(screamingface): cover access and seed preflight integration (this ledger's commit); Refs: OME-1042.
- **Deviations:** no artificial RED for already-correct combined behavior; new tests pin semantic conflict resolution. Existing approved request-count/API-snapshot changes remain intact, no prior assertions weakened. No Linear comments. PR remains open.
