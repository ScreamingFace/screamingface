---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 8E -- Engine judge scores: parse_scores in ports and the score:judge signal

## Intent

Fold the engine part of SG#13 and SR#11 on top of the unit 1 core and the unit 2 operators.
The judge reply parser (`parse_scores`, the 64 KiB cap) moves into `combine/ports.py`, because the
core cannot import a plugin. `score:judge` becomes a signal key. The core reads it from the strict
judge reply, one number for each member. A vote can then use it as a weight.
Branch `e4a-judge-pick-engine` is rebased onto `e4a-weighted-vote` (tip `dce57f326`).

## Planned changes

- Rebase repair (Commit B): `judge.py` reads `Answer.member_id`; the flow support builds
  `CombineInput(answers=...)` and maps `NoVotes` to `{"abstain": reason}`; the isolation test skips
  the vendored `_inspect_vendor`; three judge tests move to the unit 1 `Answer` fields.
- `combine/ports.py`: `JUDGE_SIGNAL`, `MAX_JUDGE_REPLY_BYTES`, `judge_reply`, `parse_scores`;
  `is_signal_key` accepts `score:judge`.
- `combine/operators/judge.py`: import the moved names; `__all__` keeps `parse_scores`.
- `combine/endpoint.py`: `_signal_values` split into `_signal_numbers`, `_accounting_numbers`,
  `_field_numbers`, plus the strict judge branch.
- Guard edits in place on stack-added tests (F8, F9).

## Test plan

A: this ledger. B: repair, no RED. C: rows 1-2 (SG#13). D: rows 3-9 (SG#13, SR#11).
E: rows 10-12 (guards, pass at once). F: results.

Rows with no RED by design: Commit B, rows 10-12 (guards, pass at once). Row 2 was RED too: the
test asserts `callable(ports.judge_reply)` first, so it failed on an assertion.

### Rebase (spec section 2.0)

`git rebase --onto e4a-weighted-vote 22f24b513 e4a-judge-pick-engine` replayed 6 commits with no
textual conflict. `git diff --stat e4a-weighted-vote HEAD -- apps/screamingface-engine/src` lists
only `combine/builtins.py`, `combine/operators/judge.py` and `world/request_parameters.py`.

Red set after the rebase (engine unit suite, 59 failed / 5951 passed):

- `test_combine_flow_golden.py::test_flow_golden_case_matches` (54 cases): `flow_input` uses
  `reading.member` / `CombineInput(readings=...)` (S2).
- `test_combine_flow_isolation.py::test_flow_operator_calls_share_no_state` (S2) and
  `::test_every_plugin_module_holds_no_mutable_state` (S3, `_inspect_vendor`).
- `test_combine_judge.py::test_label_accepts_a_member_marked_too_large` (S4),
  `::test_scores_from_numeric_values_for_rank_by_field` (S5),
  `::test_evidence_has_raw_parsed_and_presentation_order` (S6).

## Notes

- F1: no textual conflict. Six semantic breaks (S1-S6), one repair commit.
- F2: skip exactly `_inspect_vendor` (unit 2 F21) and assert it is still listed.
- F3: `parse_scores`, its helpers and the cap move to ports; `judge.py` re-exports two names.
- F4: the `score:judge` read is strict. Errata for the orchestrator: erd 4.1, `score:judge` row.
- F5: a vote weighted by `score:judge` has `evidence.judge is None`; `presentation_order == "author"`.
- F6: `scores@1` and `label@1` declare no `signal_read`.
- F7: a judge score <= 0 means the voter does not vote; all <= 0 abstains with `no_votes`.
- F8: three unit 1 stack tests move in place (Commit D).
- F9: `STU/test_signal_key_conformance.py` moves in place (Commit E).
- F10: `_signal_values` splits so each function keeps at most 3 returns.
- F11: a bad judge reply fails before any extractor runs.
- F12: after the rebase, `score:judge` hits in engine tests are the F8 files and this unit's files.

## Outcome

Commits (after the second rebase onto `e4a-weighted-vote` `d5138b026`, an SDK-only refactor): A
ledger, B repair (no RED), C rows 1-2, D rows 3-9, E rows 10-12, F this record.

RED seen: rows 1-2 (assertion on `ports.parse_scores` / `callable(judge_reply)`); row 3
(`is_signal_key` False); rows 5-9 (`combine_spec_invalid`, "unknown signal"); the three F8 edits
failed before `is_signal_key` accepted the key.

Gates (base `e4a-weighted-vote`):

- engine, `--skip-append-only`: ruff check, ruff format, pyright, check_layering, pytest with
  coverage all green.
- engine, with append-only: offenders are exactly the three F8 files `test_combine_ports.py`,
  `test_combine_signals.py`, `test_combine_spec.py` (stack-added at unit 1, edited in place).
  F9 `STU/test_signal_key_conformance.py` is stack-added at unit 4 and is not flagged in the
  engine run; it is covered by the SDK run with `--skip-append-only`.
- screamingface (SDK), `--skip-append-only`: all green. repo: all green.

Errata for the orchestrator:

- F4: erd 4.1, `score:judge` row. The judge reply is read strictly; there is no "None when the
  reducer has no judge".
- F5: a vote weighted by `score:judge` has `evidence.judge is None`.

Follow-up (8S): drop unit 7's SDK refusal of `score:judge` weights.
