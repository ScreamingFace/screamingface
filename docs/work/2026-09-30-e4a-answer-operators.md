---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-30
finished:
---

# e4a-answer-operators — the 15 v1 answer operators and their golden fixtures (epic OME-1289)

## Intent

E4a combines member answers without a synthesizer model. Unit 2 builds the pure operators the
combine endpoint runs: 5 extractors, 3 normalizers, 3 reducers and 4 selectors, each with a
frozen golden fixture. A plugin imports only `combine.ports` and the stdlib. PHASE A (this
ledger section) builds the operators, fixtures and tests against the module `OPERATORS` tuples.
PHASE B (after the rebase on the core unit) adds `combine/builtins.py` wiring, OP-1 and the
hash-seed determinism test.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/combine/operators/{__init__,extract,normalize,reduce,select}.py`
- `apps/screamingface-engine/tests/unit/fixtures/combine/<id>.json` (15 files)
- tests `test_combine_normalizers.py`, `test_combine_extractors.py`, `test_combine_reduce_select.py`,
  `test_combine_operator_isolation.py`, `test_combine_operators_golden.py`
- support module `tests/unit/combine_golden_support.py` (shared golden runner; not in the spec list)

## Test plan

- OP-3, OP-16, OP-17 numeric; OP-4 thousands; OP-5 text; OP-H3, OP-6..OP-10 extractors;
  OP-2 hostile 1 MiB timing; reduce/select tests with OP-11, OP-12, OP-13; OP-18 isolation.
- A golden test runs every fixture against the module `OPERATORS` tuples now (PHASE A).
- CHAR tests pass at once by design: none in this unit; every test is written RED first.

## Acceptance

- All 15 operators match their hand-computed golden fixtures; hostile input ends in < 50 ms.

## Outcome (fill at the end — required before COMMIT)

PHASE A (operators, fixtures, tests; no `builtins.py`). PHASE B is still open.

- **Actual files:** the 5 plugin modules; 15 fixtures; 5 test files; `tests/unit/combine_golden_support.py`
  (shared runner, added beyond the spec list so OP-1 and OP-18 use one runner); this ledger.
- **RED/GREEN:** each test was written against a skeleton (right signatures, wrong bodies) and
  failed on assertions (135 failed, 20 passed: structure tests and the timing test pass against a
  skeleton by design) before the operators were written. OP-18(b) turned RED once for the right
  reason when a `str.maketrans` dict (a module-level mutable dict) was found; fixed with a regex.
- **Commits:** c6259b820 feat(engine): add the v1 combine answer operators;
  2f597cba1 test(engine): pin the v1 combine answer operators with golden fixtures.
- **Gates:** `run_gates.py screamingface-engine` WITH the append-only check (vs HEAD, run before
  the commits): ALL GATES GREEN, no offender. Rerun `--skip-append-only` after the commits:
  ALL GATES GREEN. `run_gates.py repo`: ALL GATES GREEN. 155 operator tests pass; worst hostile
  1 MiB extractor run is 2.7 ms.
- **Deviations:** `json_field@1` returns `not_json` when the field holds a number JSON decodes to
  inf (1e999), because `canonical_json` rejects it (the spec is silent). `value@1`/`nearest@1`
  raise `SpecInvalid` when the statistic is missing, and `mode@1`/`median@1` raise it when a voter
  has no extracted value (the spec is silent). Sort key uses `-score` inside `DECIMAL_CONTEXT`.
