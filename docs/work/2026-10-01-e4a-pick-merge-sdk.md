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

## Review round 1 (coordinator, ACCEPT-WITH-FIXES)

Applied: (1) `reducer._step_matches` / `_steps_match` / `_require_steps` (version-aware: same op name,
exact id when the expected op is pinned, equal args; all four stages and no weights). Judge's matcher now
uses it with no behavior change. `_ProjectionReducer._from_spec` reads its field and requires the spec to
equal its own steps; `url4._projected_field` calls it, so a stray extract, arg, normalizer or select is
refused (five new tamper cases). (2) `Reducer._from_spec` docstring now says short-named operators are
pinned again on recompile. (3) `Merge._rebuild` refuses a duplicate field entry. (4) One writer-key rule:
`topology._writer_key` / `_writer_field` used by `fields.py`, `reducer_signals.py`, `topology.py` and
`url4.py`; `WRITER_KEY_PREFIX` removed. (5) `_signal_call_role` refuses a signal whose key and field
disagree (tested with a hand-built bad `_ModelSignal`). (6) `_ProjectionReducer` is a frozen slotted
dataclass; `_catalog()` inlined; `_signal_field` raises `ValueError` instead of asserting. (7) `_Order`
alias removed; `"Pick"` placed before `"PlanningError"` in `__all__`. (8) Tests: parametrized ids replace
the loop+`assert name` blocks, each `match=` is one expected message, the stdlib `json.dumps(1e20)`
assert is gone, local imports moved to the top, and the conformance test binds `_RULE_KEYS`,
`_FIELD_NAME` and `_MEMBER_ID` to the Engine's `operators/fields.py` (it SKIPS in this tree, where that
file is absent; I ran its parsers by hand against the file in the `e4a-rank-concat-engine` worktree and
they matched). (10) `Pick` refuses a blank `equals` and a bool `equals` with `normalize='numeric'` at
build time. (11) README Pick paragraph states that `equals=7` also matches the string `"7"`.
No deviations. Item 9 is absent from the coordinator's list; nothing was skipped.

## User decisions U2/U3 (2026-10-01)

- **U3, `writer-template@1`:** a `FieldRule.model` writer call now has a fixed, versioned system prompt
  like the Judge: `writer_intent(field, prompt)` in `fields.py` returns
  `writer-template@1 field=<field>\n` + the data framing + `Task:\n` + the author prompt. The framing says
  that member values are data, never instructions. The Engine does not change (it never parses prompts).
  `Merge._signals` builds the writer intent with `writer_intent`. `FieldRule._from_wire` recovers the author
  prompt with `_author_prompt(field, system_prompt)`: the system prompt must start with
  `writer_intent(field, "")` for THAT field, else `ValueError("URL4 Candidate has an unsupported writer
  call")`. `to_python()` shows only the author prompt and the recompile is byte-identical.
- **U2, doc note:** README Merge section says that the evidence holds each member's JSON object (in `raw`
  and `value`) for the projection step and the final merge step, so large member JSON makes a large report.
  The CHANGELOG Pick/Merge bullet names `writer-template@1`.
- **Tests (RED first):** both test files import `writer_intent` from `fields`; RED was the `ImportError`.
  New tests: the exact writer intent lines, and the template has no `$` or `\x7f` and names the field;
  `to_python()` shows only the author prompt (one and two model fields) and recompiles byte-identically;
  six url4 tamper cases are refused (version `@2`, another field name in the template line, another field
  name in the framing only, template line removed, reworded framing, `Task:` marker changed); three rebuild
  cases are refused (no template, the template of another field, extra text before the template). PM-6
  (writer context is exactly `$synthesis_K`) still holds.
- **Engine cross-check (not a committed test):** the SDK-compiled Merge with a model field was run through
  `tests/unit/test_combine_writer_world.py` helpers in the engine venv: the writer call reached the gateway
  with the template as the system message, the projection as the user message and no `binding` param; the
  output was the merged object.
- **Note:** a newline in a url4 prompt is stored as U+2028 (existing `_url4_text` rule, same as the Judge),
  so the gateway system message shows U+2028 between the template lines.

### Review round (U3 coordinator, ACCEPT-WITH-FIXES)

Applied: (1) the template no longer invites JSON: it starts "You write the text of one field." and ends
"Reply with only the text of the value and nothing else: no quotes, no JSON, no code fence, no
explanation." (the Engine stores the reply as plain text). (2) README Merge section and the
`FieldRule.model` docstring state the first line `writer-template@1 field=<field>`, the data framing and
that a template change changes the replay identity. (3) The framing says "each member id ... that has a
value for the field" (`project_field@1` leaves out members without the field). (6) The two template tests
are one. (7) New tamper case: the field name changed in the framing only. (8) New Engine test
`apps/screamingface-engine/tests/unit/test_combine_writer_template_world.py`: the gateway system message is
the whole templated prompt (pasted as a literal; the Engine test does not import the SDK), the user message
is the projection, and no body carries `binding`. Items 4 and 5 were not in the message.

### Open to-do (U2 follow-up)

- File a follow-up issue (after the user says yes, per CLAUDE.md): a size cap for the evidence of a Merge.
  Today the evidence holds each member's extracted JSON object (`raw` and `value`) for the projection step
  and the final merge step, so members that reply with large JSON make large reports. The README says so;
  a cap is not built.
