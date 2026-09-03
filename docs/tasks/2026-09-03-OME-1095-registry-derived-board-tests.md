---
id: OME-1095
linear_url: https://linear.app/openmined/issue/OME-1095/derive-the-hand-listed-benchmark-board-tuples-in-engine-tests-from-the
status: in_progress
type:
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-03
closed:
---

# Derive the hand-listed benchmark board tuples in engine tests from the registry

The engine has one registry of benchmark boards (`BUILTIN_BENCHMARKS` / `BUILTIN_DEPLOYMENT`
in `benchmarks/builtins.py`). Four engine test files kept their own copies of that list: an
exact six-id tuple, a board -> asset-bundle map, a board -> focus map and a board -> dataset
map. Every new board meant editing them by hand, which is the opposite of the epic's promise
(one author module plus a dataset mapping, zero edits to shared tests).

This unit makes the cross-benchmark tests iterate the registry and assert per-board
invariants derived from each board's own registration, so a seventh board extends the suite
by existing.

Scope guard: tests only, no production code. The e2e `BOARDS` list in
`packages/screamingface/tests/e2e/test_boards.py` is out of scope (OME-1098).

## Acceptance

- No engine test file contains a hand-typed tuple or map of board ids.
- The per-board checks are pure functions of a registration, proven by running them over a
  throwaway board the registry has never seen.
- The "exactly the registered boards are public" guarantee survives as a registry-derived
  assertion.
