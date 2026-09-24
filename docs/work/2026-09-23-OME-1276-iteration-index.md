---
ticket: OME-1276
stack: url4
status: in_progress
started: 2026-09-23
finished:
---

# OME-1276 — Expose a native iteration index in URL4

## Intent

Implement the user-approved SDK iteration index and publish a draft PR. Initial ticket
filing preceded implementation; the owner subsequently approved implementation and native
`$index` precedence inside iterations. Outside iterations, named bindings remain unchanged.

## Planned changes

Enumerate selected rows before scheduling, bind the index in immutable row scope, and
resolve it through existing reference substitution. Keep index references out of enclosing
iteration dependency capture. Add regression tests and document the compatibility boundary.
No benchmark or Client changes belong to this unit.

## Test plan

TDD through actual SDK execution: slicing, concurrency, failures, retries, nested capture,
text/AST parity, empty selections, escaping and named bindings. Run full URL4 quality gates
and independent spec/standards review before committing.

## Acceptance

Stable zero-based post-slice indices, no renumbering after failed rows, no outside-scope
leakage; SDK-only change published as a draft. Ticket remains In Progress until review.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** three DAG runtime files; one new regression test module; SDK README;
  spec, plan, task mirror and this ledger.
- **TDD:** initial RED included failing native-index checks; all 20 focused tests pass.
- **Gates:** full URL4 gate runner passes append-only tests, lint, format, pyright and the
  complete pytest suite with the 95% coverage threshold.
- **Review:** independent spec and standards reviews found no blocking issues. Both flagged
  one stale dependency-filter comment; corrected, with lint and format rechecked.
- **Deviations:** no parser grammar change needed because `$index` already parses as a
  reference. Reserved meaning inside iteration is an explicitly approved SDK extension.
- **Delivery:** draft PR pending; no benchmark migration or merge in this unit.
