---
ticket: OME-1095
stack: screamingface-engine
status: done
started: 2026-09-03
finished: 2026-09-03
---

# OME-1095 — Derive the hand-listed benchmark board tuples in engine tests from the registry

## Intent

Cross-benchmark engine tests carry their own copies of the board list — an exact six-id
tuple plus board->bundle, board->focus and board->dataset maps. Adding a board means editing
them by hand, so the epic's deletion test ("a new benchmark is one author module and a
dataset mapping, zero edits to shared tests") is unmeasurable. Make the shared tests iterate
`BUILTIN_DEPLOYMENT` / `BUILTIN_BENCHMARKS` and assert invariants derived from each board's
own registration.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_benchmark_protocol.py` — the six-id tuple becomes
  a registry-derived "the catalogue publishes exactly the registered boards, in stable id
  order" assertion.
- `apps/screamingface-engine/tests/unit/test_benchmark_deployment.py` — the board->bundle map
  becomes a parametrized provenance check (a board's bundle is the `ASSET_BUNDLE_ID` exported
  by the module that defines its installer, i.e. the directory the board actually reads), plus
  a throwaway-board test proving the check is a pure function of a registration; the
  hand-typed `FAMILY_PACKAGES` set becomes the families of the registered boards' installers.
- `apps/screamingface-engine/tests/unit/test_benchmark_display_metadata.py` — the focus and
  dataset maps become per-board invariants: every board declares a focus, focus lines are
  unique across boards (that is what separates two boards over one dataset), and boards that
  share an asset bundle declare the same dataset link.

## Test plan

Tests are the deliverable. Each replacement must fail for the reason it names:
- catalogue vs registry: a registered board missing from the catalogue, or an unsorted id order.
- bundle provenance: a board registered against another family's bundle.
- family guard: a family package with a `prepare.py` that no registered board uses.
- display: a board without a focus; two boards sharing a focus line; two boards on one bundle
  declaring different dataset links.
Verified by running the four affected test modules (free, no paid models).

## Acceptance

- No engine test file contains a hand-typed tuple or map of board ids.
- Per-board checks run over a throwaway registration without edits.
- No production code changes.

## Outcome

- **Actual files:** as planned — `tests/unit/test_benchmark_protocol.py`,
  `tests/unit/test_benchmark_deployment.py`, `tests/unit/test_benchmark_display_metadata.py`.
  No production code touched.
- **Commits:** see the PR (`OME-1095-registry-derived-board-tests`).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` — ALL GATES GREEN
  (2280 passed, 5 skipped). The append-only check is skipped BY DESIGN for this unit: rewriting
  the hand-listed prior tests IS the deliverable the ticket approves, and the skip flag is the
  runner's own escape hatch rather than an edit to the gate.
- **Review round 1 (request-changes), both blockers closed:** removing the six-id tuple left
  board MEMBERSHIP uncovered — deleting `draco-3pass` from `builtins.py` passed the whole
  suite, because the catalogue test compares the route against the same registrations the
  registry is built from. And "one bundle, one dataset link" could not catch a family-wide
  wrong value, since each family declares one shared `*_DATASET_URL` its boards both read.
  Both facts are per-board, so both are now pinned in each board's OWN definition test
  (`test_draco_3pass_definition.py`, `test_gdpval_definition.py`,
  `test_ifeval_official_identity.py`, `test_healthbench_definition.py`) — one line per new
  board in the author's module, so the deletion test still holds. Verified: unregistering
  `draco-3pass` or `gdpval-text`, pointing `DRACO_DATASET_URL` at another dataset, and giving
  IFEval a link each now fail. Two vacuous assertions were deleted and one over-claiming
  docstring corrected in the same round.
- **Deviations:** each replacement was mutation-verified rather than trusted — a board
  registered against another family's bundle, an orphan preparer family, two boards sharing a
  focus line, two dataset links under one bundle, and a board dropped by the catalogue route
  each fail exactly one new test. The first draft's registry-vs-catalogue assertion was
  tautological (the registry derives from the registrations and sorts its own ids), so it now
  reads the catalogue over HTTP, where a route that drops a board is caught.
