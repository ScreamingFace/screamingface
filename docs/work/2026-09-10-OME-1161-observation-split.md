---
ticket: OME-1161
stack: screamingface-engine
status: done
started: 2026-09-10
finished: 2026-09-10
---

# Shared delivery ledger — OME-1161

## Intent and plan

Owner requested a docs PR first, then sequential main-based code PRs. Every PR is capped at
500 added plus deleted lines including tests/docs. Keep one shared artifact in each folder,
retain justifications, and preserve the complete implementation while splitting review scope.

## Completed preparation

- Complete activity preserved at 01b3a0f1; integrated foundation at 1344cb62; ports at f9aa283f.
  Named local branches and restoration boundaries are recorded in the shared plan.
- Full Engine gates passed on each preserved checkpoint. The ports checkpoint includes 16
  focused fault/isolation tests; the integrated foundation includes 22 focused tests. These
  results are preparation evidence, not claims that code ships in this documentation PR.
- Independent review found no remaining confirmed issues in the preserved foundation/ports.
- PR 897 now contains only this ledger, the shared spec, plan and task mirror. No runtime,
  configuration or test changes remain in its final diff. No later PR is open.

## Verification and remaining work

Verified: docs-only diff, relative links, one file per folder and 177 changed lines (cap 500).
After docs merge, extract each code unit from updated main and repeat gates/review. Existing
pre-PR tests remain intact; deferred tests stay with their preserved implementation.
OME-1161 remains open. Append subsequent delivery outcomes to this same ledger.


## Code unit 1 — observation ports (2026-09-10)

Extracted ports/tests from f9aa283f after docs merge af58b5c1, on a fresh main worktree.
Interface docstrings explain lifecycle obligations; no execution hooks or activity ship.
RED reproduced the absent module, then wrong-run fault attribution and lost bind errors.
Owner-approved revision uses explicit fault ownership, faithful step-exception teardown
and one guard for synchronous/awaited callbacks. Nested execution isolation is unchanged.
All 22 focused tests and full Engine gates pass; both reviews found no remaining issues.
Full PR: 496 changed lines, including shared artifacts. The overall feature remains open.

## Code unit 2 — execution integration (2026-09-11)

Owner approved a temporary stack on PR 899, to rebase onto main after its merge.
Intent: connect generic observations to existing execution facts without activity imports.
Planned files: connector, executor, main composition and operation wrapper; integration tests.
Acceptance: real retry/outcome delivery, per-run isolation, cross-task cleanup, unchanged
requests/accounting/cancellation/operator diagnostics with no plugin. Keep this diff under 500
changed lines, retain shared artifacts, run focused RED then full Engine gates and review.
Outcome: five wiring regressions failed before integration; review found iterator-creation
cleanup leakage, reproduced RED and fixed. All 30 focused cases and full Engine gates pass
(append-only vs 96b15be0, Ruff lint/format, Pyright, layering, full pytest/coverage).
Both reviews have no remaining findings. Existing tests remain intact. The narrow integration
keeps policy in the future plugin; no new dependencies or public wire schema changes.
Commit: feat: connect optional observers to Engine execution. Activity remains a separate delivery.

## Unstack integration (2026-09-14)

PR 899 merged at dcaba228. Rebased only the integration commit onto updated main without
conflicts, preserving intervening execution changes. Full Engine gates passed against main
(append-only, Ruff, Pyright, layering, full pytest/coverage). PR 915 targets main; no new scope.

## OME-1201 — observer latency contract (2026-09-14)

Owner approved adding the rule to PR 915. Document prompt inline callbacks and separate
async cleanup responsibilities; add a caller-task/ordering test. No runtime enforcement.
Validate focused tests and full gates, then rebase PR 931 onto the updated integration head.
Characterization test passes without runtime changes; full Engine gates pass. Review found
no issues. OME-1201 remains open until PR 915 merges.

## Plugin split — contract and admission (2026-09-14)

Owner requested shrinking PR 931 to the first review boundary. Complete plugin and all its
tests are preserved at 2bc435bb on OME-1161-complete-plugin-preserved.
Plan: retain only contract/session modules and direct vocabulary/admission tests; defer
operation scopes, adapter, timers, configuration and end-to-end tests with their implementation.
No existing pre-931 tests change. This unit does not register or enable activity.
Acceptance: field safety, state validation, exact reserve/refill, suppression/revocation,
concurrent admission and multi-day recovery; full Engine gates against PR 915.
Outcome: 29 direct tests pass and full Engine gates pass against ed8ee03e (append-only,
Ruff lint/format, Pyright, layering, full pytest/coverage). Both reviews found no issues.
The extracted production code is unchanged; no prior tests or execution behavior change.
Follow-ups: lifecycle/adapter, then deployment/end-to-end verification.
