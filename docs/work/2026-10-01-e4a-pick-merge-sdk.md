---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# e4a-pick-merge-sdk — sf.Pick, sf.Merge and sf.FieldRule (OME-1289, unit 9 SDK)

## Intent

`sf.Pick(field, order=|equals=)` compiles to one combine call (`json_field@1` extract, `numeric@1` or
`text@1` normalizer, `values@1` reduce, `by_field@1` select) and the answer is the chosen member's JSON
byte for byte. `sf.Merge(fields={...: sf.FieldRule...})` compiles to one combine call
(`json_object@1`, `field_rules@1`, `built@1`). A `FieldRule.model(...)` field adds, per field, a
projection combine call (`project_field@1`) and one writer model call (`writer_N`) that sees only that
projection; the final merge call reads `signals: {writer_<field>: $writer_N}`. This unit reuses the unit
8 seams (`_append_combine`, `_spec_steps`, `_signal_role`, `OPERATION_BINDING_PARAM`,
`_operation_shape`, `_next_binding`). The Engine half is on another branch, so tests use fixture
catalogs.

## Planned changes

- New src: `fields.py` (`Pick`, `Merge`, `FieldRule`).
- Edited src: `reducer.py` (`_ModelSignal.field`), `_evaluation/reducer_signals.py` (projection and
  writer branch, `_ProjectionReducer`), `_evaluation/topology.py` (writer role, projection node,
  `_TopologyBinding.signal`, `_operation_shape(node, signal)`), `url4.py` (projection field, writer
  binding check), `_evaluation/url4.py` (projection owner names, pass `binding.signal`), `__init__.py`,
  `CHANGELOG.md`, `README.md`.
- New tests: `tests/test_pick_merge_reducers.py`, `tests/test_merge_writer_compile.py`,
  `tests/test_pick_merge_url4_round_trip.py`, `tests/unit/test_signal_key_conformance.py`.
- `tests/public_surface_snapshot.json` regenerated (the one allowed append-only offender).
- NOT touched: `_evaluation/candidate.py`, `_combine_flow_fixtures.py`, any existing test.

## Test plan

FieldRule constructors and repr; PM-12 out of range at build; Merge/Pick argument validation; exact spec
literals for Pick max/min/equals and Merge without model fields (PM-1/3/15 compile); PM-7 compile of
projection + writer + final merge (source order, bindings, params, context, operations, models,
topology JSON); PM-6 writer context is only `$synthesis_K`; two model fields numbering; url4 round trip
(to_python, recompile, linked replay, corrective); tampering refusals; signal key grammar conformance
against the Engine `_SIGNAL`; writer operation accounting row. CHAR: existing tests stay green, SL-1
bytes unchanged.

## Acceptance

- `screamingface --base e4a-judge-pick-sdk` with append-only: only `public_surface_snapshot.json`.
- `screamingface --skip-append-only` green, `repo` green.
- Cross-check: SDK-emitted Pick, Merge, Merge+model field run through the Engine `parse_spec`,
  `parse_context`, `run_combine` (not a committed test).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; nothing unlisted, `_evaluation/candidate.py` not touched. New:
  `fields.py`, `tests/test_pick_merge_reducers.py`, `tests/test_merge_writer_compile.py`,
  `tests/test_pick_merge_url4_round_trip.py`, `tests/unit/test_signal_key_conformance.py`. Edited:
  `reducer.py` (`_ModelSignal.field`), `_evaluation/reducer_signals.py` (`_ProjectionReducer`,
  `_projection_source`, writer branch), `_evaluation/topology.py` (writer role, `_SignalTopology.projection`,
  `_TopologyBinding.signal`, `_operation_shape(node, signal)`, `_signal_role` writer key),
  `url4.py` (`_projected_field`), `_evaluation/url4.py`, `__init__.py`, `CHANGELOG.md`, `README.md`,
  `tests/public_surface_snapshot.json` (regenerated).
- **RED/GREEN:** RED first on a skeleton `fields.py` (constructors that store nothing): 49 of 50 tests failed
  on assertions (the conformance test failed on the missing writer keys); 1 passed at once (a CHAR-style
  tamper case that the unit 8 decoder already refuses). Then GREEN with the real code.
  Mutation checks (temporary, reverted): dropping the key==field check, the writer context check, the
  decoder's projection key rule, and the writer binding check each fail at least one test; a new tamper case
  (writer context wrapped) was added because the context check was first uncovered.
- **Cross-check with the Engine (not a committed test):** SDK-compiled Pick (max, equals+text), Merge without
  model fields (with a `not_json` member), and Merge with a model field were run through the Engine worktree
  (`e4a-rank-concat-engine`) `parse_spec`, `parse_context` and `run_combine(BUILTIN_OPERATORS)`. All accepted;
  outputs were as expected (see the final report).
- **Gates:** `screamingface --base e4a-judge-pick-sdk` with append-only: only offender
  `tests/public_surface_snapshot.json` (expected). `--skip-append-only`: ALL GATES GREEN (ruff, format,
  pyright, pytest with coverage >= 95, notebooks, build, distribution); the two known flaky tests did not
  fail. `repo`: ALL GATES GREEN.
- **Deviations:** (1) `FieldRule` stores the writer route as `route`, not `model`: a slotted dataclass field
  named `model` replaces the classmethod `FieldRule.model(...)`. (2) `Merge.__eq__` is order-aware (the field
  order is the spec order). (3) `Pick`/`Merge` public signatures show `Literal['max','min']` inline for the
  snapshot. (4) Test helpers are imported from `test_judge_reducer.py`, `test_judge_url4_round_trip.py` and
  `test_judge_report.py` (existing practice), so no new helper file. (5) Extra checks beyond the spec: the
  writer call's context must be exactly `$<projection>` when a url4 is read back, and all projection specs are
  built before any source is appended (a catalog without `project_field` fails before state changes).
