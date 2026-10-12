---
ticket: OME-1587
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 9E -- Engine pick and merge: abstain on no usable value

## Intent

Fold the engine part of AB#4 on top of the unit 1 core and the unit 2 and 8E operators. A merge
field rule, a projection or a by_field equals pick that finds no usable value does not fail the
case any more: it asks the core to abstain (`NoVotes`, reason `no_votes`). The field operators
also move onto the core's `Answer` port and the shared ports helpers (`decode_json_reply`,
`FIELD_PATH`).
Branch `e4a-pick-merge-engine` is rebased onto `e4a-judge-pick-engine` (tip `0fa1f9ce2`).

## Planned changes

- Rebase repair (Commit B): `operators/fields.py` imports `Answer` and reads `.member_id`; the
  evidence rows in `test_combine_fields.py` use `(status, reason)`.
- Commit C: the six `combine_no_votes` goldens and the `NoVotes` tests become abstain checks. The
  raise sites say `reason="no_votes"` explicitly. A new integration test pins the F8 mark.
- Commit D: `values@1` requires a field path (`FIELD_PATH`); `json_object@1` is pinned to
  `decode_json_reply`; the two docstrings gain "plus ``re2``".

## Test plan

A: this ledger. B: repair, no RED. C: rows 1-6 (guards, they pass at once: F4). D: row 7 (RED),
rows 8-9 (guard, docstring). E: results. A later small commit types the operator-level calls
(pyright found them; the tests were green).

Rows with no RED by design: Commit B; Commit C (F4: the behavior change happened in the unit 1
core, the raise sites already call `NoVotes`); row 8 (guard); row 9 (docstring).

### Rebase (spec section 2.0)

`git rebase --onto e4a-judge-pick-engine ce352f89f e4a-pick-merge-engine` replayed 5 commits.
One textual conflict, in `4ef2be092`, `combine/operators/extract.py`, both hunks: HEAD's whole
file was kept (it holds the regex and Inspect operators and imports `decode_json_reply` from
ports; `_decode` is gone). `json_object` was inserted right after `json_field`, and its
descriptor right after the `json_field` descriptor, with `decoded = decode_json_reply(text)`.
`builtins.py`, `ports.py` and `operators/__init__.py` applied without a conflict.
`git diff e4a-judge-pick-engine HEAD -- .../extract.py` shows only `json_object` and its
descriptor; `git grep -n "_decode\b" -- .../extract.py` prints nothing.

Red set right after the rebase: the whole built-in registry fails to import
(`fields.py` imports `MemberReading`, which unit 1 removed), so every engine test that imports
`combine.builtins` errors at collection (S1).

## Notes

- F1: the `extract.py` conflict, resolved as above with `decode_json_reply`.
- F2: `ports.py` and `operators/__init__.py` apply cleanly; Commit D adds "plus ``re2``".
- F3: semantic breaks S1 (`fields.py`), S2 (four evidence rows in `test_combine_fields.py`),
  S3 (six goldens and six `pytest.raises(NoVotes)` assertions made through `run`, red by design
  until Commit C).
- F4: AB#4 rows are guards. The only code change is an explicit `reason="no_votes"`.
- F5: AB-D4 covers `majority`, `max` and `union` only. `from_member` null and a `model` `""` are
  values (PM-14 goldens). Errata for the orchestrator: AB-D4 wording.
- F6: a reduce raise (field_rules, project_field) gives `fields is None`; a select raise (by_field
  equals) keeps the `values@1` reading.
- F7: `values@1` requires `FIELD_PATH.fullmatch(field)` (still at most 256 chars). `_FIELD`
  (merge and project field names) stays as it is.
- F8: a final merge that abstains marks the invocation (unit 3); an integration guard pins it.
- F9: `test_failures_name_the_rule_and_never_echo_values` checks the message at operator level and
  checks that the abstain evidence JSON, except `members` (extracted values by design), holds no
  `SECRET` (see the Outcome F9 note).
- F10: `json_object@1.json` keeps the stage vocabulary; no change.

## Outcome

Rebased twice: first onto `e4a-judge-pick-engine` `0fa1f9ce2` (the conflict above), then onto its
review-fix tip `4799df8d4` (`git rebase --onto e4a-judge-pick-engine 0fa1f9ce2`), which applied
with no conflict.

Red set after Commit B (the S3 set, by design): the six golden cases (`field_rules@1` x4,
`by_field@1`, `project_field@1`) and four tests in `test_combine_fields.py` (the `pytest.raises`
assertions made through `run`). Commit C turns them green.

RED seen: row 7 only (`values_field_is_a_field_path` did not raise; the two new golden cases
returned a reduction instead of `combine_spec_invalid`). Rows without RED: Commit B (repair),
Commit C rows 1-6 (guards: the abstain came from the unit 1 core, F4), row 8 (guard), row 9
(docstring).

Deviations from the spec text:

- Row 3 is two tests, not one parametrized test: the four reduce cases check `fields is None`, the
  by_field case checks the kept `values@1` reading (F6).
- F9: the evidence keeps each member's extracted value (`members[].raw` and `value`, as
  `evidence.py` allows), so a whole-JSON `SECRET` check cannot hold for the merge case. The test
  checks every evidence key except `members`, and for the by_field target (which is not a member
  value) that the whole evidence JSON holds no `SECRET`.

Gates (base `e4a-judge-pick-engine`):

- engine, `--skip-append-only`: ruff check, ruff format, pyright, check_layering, pytest with
  coverage all green.
- engine, with append-only: ALL GATES GREEN. The offender list is empty, as expected.
- screamingface (SDK): not run, no SDK file changed. repo: ALL GATES GREEN.

Errata for the orchestrator: AB-D4 covers `majority`, `max` and `union` only. `from_member` null
and a `model` `""` are values (F5). This erratum is already GE16 in the docs branch.
