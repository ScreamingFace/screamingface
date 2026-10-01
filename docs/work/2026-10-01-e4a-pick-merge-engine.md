---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# e4a-pick-merge-engine — pick and merge operators (json_object, values, by_field, field_rules, project_field, built)

## Intent

OME-1289 (E4a) unit 9, engine half. Members that return JSON can be joined by declared rules, not
rewritten by a model. This unit adds the extractor `json_object@1` (whole reply, or last ```json
fence, as one canonical JSON object; anything else is `not_json`) and the field operators
`values@1`, `by_field@1` (Pick: max, min or equals, the answer is the member's own JSON), and
`field_rules@1`, `project_field@1`, `built@1` (Merge: majority, max, from_member, union, model;
the writer signal key is `writer_<field>`). Field readings hold JSON values only. The merged
object holds only the declared fields, in canonical JSON. No per-reducer operator rule is added
to `spec.py` and `ports.py` does not change.

## Planned changes

- New: `combine/operators/fields.py`. Modify: `combine/operators/extract.py` (append
  `json_object@1`), `combine/builtins.py` (one import name, one `*fields.OPERATORS` line).
- New fixtures: `tests/unit/fixtures/combine/json_object@1.json` (top level, unit 2 harness) and
  `tests/unit/fixtures/combine/flow/{values@1,by_field@1,field_rules@1,project_field@1,built@1}.json`.
- New tests: `test_combine_fields.py`, `test_combine_fields_determinism.py`,
  `combine_fields_scenarios.py`, `test_combine_writer_world.py`.
- Not touched: `ports.py`, `spec.py`, any test file from units 2, 3 and 8.

## Test plan

- RED first for the right reason (assertion, after a skeleton `fields.py` and a skeleton
  `json_object`): json_object cases; PM-1/OP-15 pick; PM-2; PM-9; PM-10; PM-15; PM-3/4/5/13 merge
  rules; PM-14; PM-11; PM-6 engine; model field; PM-D8; goldens; FW-3 hash seeds.
- Integration (aigateway world): PM-H4/PM-6/EV-H3 writer sees only the projection; PM-8 writer
  failure; catalog lists the six ids.
- OP-1 (rglob exact set, unit 2) turns RED when the built-ins are wired and stays RED until every
  new built-in has its fixture file.

## Acceptance

- The unit 9 engine tests pass; both gate runs are green; no append-only offender.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Source: `combine/operators/fields.py` (new), `combine/operators/
  extract.py` (`json_object@1`), `combine/builtins.py` (one import name, one `*fields.OPERATORS`
  line). Fixtures: `fixtures/combine/json_object@1.json` and `fixtures/combine/flow/{values,
  by_field,field_rules,project_field,built}@1.json`. Tests: `test_combine_fields.py`,
  `test_combine_fields_determinism.py`, `combine_fields_scenarios.py`,
  `test_combine_writer_world.py`. Not touched: `ports.py`, `spec.py`, any unit 2, 3 or 8 test.
- **Test ids (RED seen -> GREEN):**
  - json_object cases (`test_json_object_reads_a_whole_or_fenced_object`): RED yes (skeleton
    rejected every object), GREEN. The reject cases (`..._rejects_anything_that_is_not_one_object`)
    passed at once with the skeleton: CHAR by design.
  - PM-1/OP-15 `test_pick_max_min_equals_returns_member_json_byte_for_byte`, PM-2
    `test_non_json_member_is_skipped_and_reported`, PM-9 `test_all_members_unusable_fails_with_
    combine_no_votes`, PM-10 `test_pick_tie_goes_to_author_order`, PM-15 `test_pick_equals_uses_
    declared_normalizer`, PM-3/4/5/13 `test_merge_rules_majority_max_from_member_union` and
    `test_merge_output_has_only_declared_fields`, PM-14 `test_from_member_not_json_gives_null_
    field_and_reason`, PM-11 `test_merged_json_is_canonical`, PM-6 engine `test_projection_
    returns_only_the_field_values`, `test_model_field_takes_the_writer_text`, PM-D8
    `test_large_member_json_is_too_large_and_skipped`: RED yes, GREEN.
  - `test_from_member_outside_the_spec_members_is_a_spec_error`,
    `test_projection_with_no_member_field_fails_with_no_votes`: a false pass with the skeleton
    (the skeleton operators took no args and raised `combine_spec_invalid`), real GREEN after.
  - OP-1 (unit 2, rglob exact set): RED yes after wiring the built-ins, GREEN once the six
    fixture files existed (also shown by removing a fixture again).
  - Goldens (`test_flow_golden_case_matches` over the five flow fixtures and the unit 2 tests over
    `json_object@1.json`): the `expect` values were typed by hand before the first run and all
    passed on that run.
  - Written after the code and GREEN at once (CHAR / integration): FW-3
    `test_pick_and_merge_are_identical_across_hash_seeds` (20 seeds) and its three scenario
    checks; `test_writer_sees_only_the_projection` (PM-H4, PM-6), `test_writer_on_a_member_route_
    keeps_every_operation` (EV-H3), `test_writer_failure_fails_case_without_partial_object`
    (PM-8), `test_catalog_lists_the_field_operators`; `test_field_rules_takes_at_most_64_fields`;
    `test_failures_name_the_rule_and_never_echo_values`.
- **Commits** (after the coordinator rebased the branch onto unit 8 tip `4a2182430`):
  `eed053b14` feat(engine): add the pick and merge field operators; `1a563f4be` test(engine):
  cover a voter value that is not JSON in the field goldens; `978e1bb64` docs(work): record the
  e4a pick merge engine ledger (the first ledger); `1477f66b9` fix(engine): compare real JSON
  numbers as numbers and harden the field operators (review round 1); the last commit of the
  branch, docs(work), carries this updated ledger.
- **Gates (after review round 1, base `e4a-judge-pick-engine` at `4a2182430`):**
  `run_gates.py screamingface-engine --base e4a-judge-pick-engine`: ALL GATES GREEN, append-only
  check clean (no offenders). `--skip-append-only`: ALL GATES GREEN. `repo`: ALL GATES GREEN.
  `fields.py` and `extract.py` are at 100% line and branch coverage.
- **Review round 1 (coordinator, ACCEPT-WITH-FIXES), commit `1477f66b9`:**
  - Item 1: the max rule reads a real JSON int or float (not bool) as `Decimal(repr(v))`, and only
    a string goes through `numeric@1`. RED first: goldens `1e100` vs `3`, `10**70` vs `3`,
    `1e-100` vs `0` failed (numeric@1 refuses a 2-digit-plus exponent and more than 64 chars),
    GREEN after the fix.
  - Item 3: `_object` runs `canonical_json` and turns an infinite number from another extractor
    (`whole@1` + `{"x":1e999}`) into `combine_spec_invalid`. RED first (`ValueError` escaped),
    GREEN. Item 4: the `operators/__init__.py` and `ports.py` docstrings now allow a sibling
    plugin's pure functions (never its `OPERATORS`).
  - Item 6: goldens for a union of empty lists and a union whose items are all rejected (both
    `[]`), plus a golden for the `"true"` / `true` key conflation: CHAR, GREEN at once. Item 7:
    AIDEV-NOTE on the conflation, golden renamed to "majority without normalizer keeps case apart".
  - Item 8: `by_field` INVARIANT docstring. Item 12: the writer `messages` list is asserted whole.
    Item 13: PM-8 pins `aigateway_http_400` and, with caplog, that the projection ran and the
    final merge call (`synthesis_1`) never did. Item 16: new `combine_fields_support.py` holds
    `step`, `pick_spec`, `merge_spec`, `project_spec`. Item 17: `_Rule` and `_Objects` private,
    `str(normalize)` casts dropped. Items 12, 13, 16 and the 6/7 goldens need no RED (they pin
    behavior that already held).
- **Deviations:** none from the spec. Two readings of the spec text are recorded here:
  (1) `union` raises `combine_no_votes` when no member has a list value (the golden "union with
  no lists"); a union whose lists are all empty, or whose items the normalizer all rejects, gives
  `[]` (pinned by goldens in round 1). (2) `values@1`, `by_field@1`, `field_rules@1` and
  `project_field@1` publish an `args_schema` (the spec lists none) so the catalog does not claim
  "no args".
- **Process deviation:** these rows were written AFTER the code, so they were GREEN at once and
  have no RED step: FW-3 `test_pick_and_merge_are_identical_across_hash_seeds` and its scenario
  checks; the world tests `test_writer_sees_only_the_projection`,
  `test_writer_on_a_member_route_keeps_every_operation`,
  `test_writer_failure_fails_case_without_partial_object` and `test_catalog_lists_the_field_
  operators`; `test_field_rules_takes_at_most_64_fields`; `test_failures_name_the_rule_and_never_
  echo_values`.
