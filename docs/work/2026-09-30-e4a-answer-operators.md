---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-09-30
finished: 2026-10-01
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

PHASE A (operators, fixtures, tests) and PHASE B (builtins wiring, OP-1, hash-seed determinism,
end-to-end tests, helper reconcile) are both done.

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
- **Deviations:** (orchestrator decision: `last_number@1` returns the whole comma run) `json_field@1` returns `not_json` when the field holds a number JSON decodes to
  inf (1e999), because `canonical_json` rejects it (the spec is silent). `value@1`/`nearest@1`
  raise `SpecInvalid` when the statistic is missing, and `mode@1`/`median@1` raise it when a voter
  has no extracted value (the spec is silent). Sort key uses `-score` inside `DECIMAL_CONTEXT`.

### Phase A review fixes (ACCEPT-WITH-FIXES)

- Median and nearest accept only `-?[0-9]+(\.[0-9]+)?`; no Decimal error escapes. A zero tally
  total raises `SpecInvalid`. The weighted_mode pre-loop is gone.
- Orchestrator decision 4: `last_number@1` returns the whole maximal digit/comma run
  (`[-\u2212]?[0-9]+(,[0-9]+)*(\.[0-9]+)?`); `numeric@1` judges the grouping. The golden for `1,23`
  changed from `23` to `1,23` (numeric: `not_numeric`). Hostile `"1,"*524288` stays far below 50 ms.
- Golden test: no hard-coded 15 and no exact-set check against the module tuples (two subset
  checks via the fixture files instead); phase B's OP-1 over BUILTIN_OPERATORS is the exact check.
- New CHAR tests that passed at once by design: hostile global decimal context (prec=2), and the
  pinned quirks (`1e999`, `1e20` -> `1e+20`, `-0.0`, repeated key, `9..`, `5$3`, boxed `a\}b}`,
  `a b`, `3.5e10`). Every hand-derived value matched the code.
- The append-only check flagged only this branch's own phase A files (edits are authorized by the
  coordinator); the gate was rerun with `--skip-append-only` and is green, as is `repo`.
- `json_field@1` `args_schema` top level is a `MappingProxyType` with a `required` tuple. The nested
  `properties` dict stays plain because `ports.catalog_entry` deep-copies the schema and a
  mappingproxy cannot be deep-copied or JSON-encoded (`ports.py` is not editable here).

### Phase B (after the rebase onto e4a-combine-core)

- Rebase clean: 321 combine/world/layering tests passed, `check_layering.py` OK (the plugins pass the
  COMBINE_CORE plugin rule). No unit 1 test asserts an empty builtins registry (only
  `test_builtin_operators_is_built_at_import`, an isinstance check).
- Step 9: `combine/builtins.py` lists the four plugin modules. OP-1
  `test_golden_outputs_match_for_every_registered_operator` was RED first on the exact-set assertion
  (the registry was empty), then GREEN. It resolves each id through `BUILTIN_OPERATORS.resolve`.
- Step 10: `test_builtin_vote_and_median_are_identical_across_hash_seeds` (seeds 0..19, byte-equal to
  the in-process result). RED first: `OperatorUnknown` (the registry was empty), then GREEN.
- End-to-end tests with hand-computed expectations (RED first, then GREEN): VT-H1 vote
  (18,18,26,18,18: member_1 text, tally 18:4 / 26:1, agreement 0.8, tie false), the same vote through
  the url4 route (one recorded call), VT-H4 median value (10,12,30,40 -> "21", built, chosen []),
  and median + nearest (member_2, tie true, agreement 0.25).
- Helper reconcile: `combine_support` = core fakes and builders; `combine_golden_support` = real
  plugin helpers, built on `combine_support.vote_spec/spec_text/context_text/run` (no copies).
  The new `hash_seed_support.py` holds the hash-seed subprocess harness. Unit 1's
  `test_combine_determinism.py` keeps its own private copy of that harness (its tests are append-only
  for this unit), so a later cleanup can point it at `hash_seed_support`.
- Deviation: the end-to-end test file `test_combine_builtin_end_to_end.py` and `hash_seed_support.py`
  are not named in the spec.
