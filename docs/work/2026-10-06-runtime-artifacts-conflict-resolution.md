---
ticket: OME-1454
stack: screamingface
status: done
started: 2026-10-06
finished: 2026-10-06
---

# Runtime artifacts — reconcile current main and review PR #1217

## Intent

Resolve PR #1217's conflict with current main, preserving persistent runtime artifact
storage and main's newer archive-savings accounting contract. Review the complete
result against the runtime spec and repository standards before pushing the update.

## Planned changes

- Incorporate main at b83b96708904d32caee2be5d30e4094e190f3a23.
- Preserve main's existing accounting tests exactly; adapt the PR's new timestamp
  regression to the renamed archive-money test and current partial-status contract.
- Retain direct assertions for spend, reported saving, archive saving and exported usage
  in the timestamp regression, avoiding whole-JSON substring matches.

## Test plan

- Run all SDK card gates against origin/main, including the append-only guard.
- Review the diff independently for documented standards and spec conformance.

## Acceptance

No unresolved conflicts, existing main tests intact, timestamp regressions passing,
SDK gates green and review findings reported to the user.

## Outcome

- **Actual files:** main integration plus the new timestamp regression and this ledger.
  Existing main accounting tests are preserved byte-for-byte; runtime production changes
  from the PR compose unchanged with main.
- **Commit:** `chore(runtime): resolve PR 1217 conflicts with main`.
- **Gates:** ALL GATES GREEN with `UV_NO_SYNC=1` and the notebook extra prepared from the
  frozen lockfile: append-only vs origin/main, Ruff lint/format, Pyright, full parallel
  pytest with unchanged 95% coverage floor, notebooks, build and distribution.
- **Reviews:** independent standards and spec reviews found no actionable defects;
  33 focused runtime/accounting regressions also passed.
- **Deviations:** incorporated main through a merge commit to finish the in-progress
  conflict resolution without rewriting existing PR history. The initial append-only
  check rejected added assertions inside an existing main test; those assertions were
  moved into the PR's new regression file, and the guard then passed without a bypass.
  No paid calls or external review comments.
