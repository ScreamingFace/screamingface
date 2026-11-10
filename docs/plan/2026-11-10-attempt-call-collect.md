# A failed Candidate call fails only its own Attempt — Implementation Plan

**Goal:** an errored Candidate call in one Attempt becomes that Attempt's failed row, carrying
the error's code, so the fold scores the Case from the tries that answered (spec
`docs/spec/2026-11-10-attempt-call-collect.md`). One PR, stacked on #1709 (OME-1856), Engine only.

**Tech stack:** Python 3.12, uv, pytest, URL4 (`iterate`, `on_error=collect`), pydantic v2.

## Tasks

- [ ] **RED, protocol:** append to `tests/unit/test_case_attempts_protocol.py` a stand-in
  Candidate that raises `ResolutionError(code="model_token_cap")` on Attempt 2 of 3; assert the
  joined row carries two envelopes and one error row in Attempt order, and the aggregate files
  Attempt 2 `failed` with code `model_token_cap`, the Case scored from Attempts 1 and 3. Add the
  gateway-code variant and the all-failed variant. Add the position test: two Cases through the
  outer cases iterate, the Candidate sees `case_index` 0 then 1 in every Attempt.
- [ ] **RED, fold numbers:** append to `tests/unit/test_attempt_fold.py` the end-to-end numbers
  through the real aggregate (`_aggregate` / `_aggregate_mean`): 4 right + 1 token cap → 0.8
  (`mean`), 1.0 (`any`); 4 right + 1 gateway error → 1.0 (both).
- [ ] **RED, contract:** in `tests/unit/test_case_attempts_contract.py`, every Attempts Benchmark's
  rendered url4 contains `$index` exactly once (the Case-level binding) and reads
  `$case_position` in each Attempt.
- [ ] **GREEN, `protocol.py`:** `_attempted_case` binds `case_position` and wraps each Attempt
  (spec D1, D2); `_numbered` rewrites the Candidate Invocation's `case_index` text.
- [ ] **GREEN, `graded_answer.py`:** `_case_attempts_route` unwraps each Attempt's one-row list.
- [ ] **GREEN, aggregation:** confirm the missing-case rung files the error row as a failed Attempt
  with the error's code; change only if the test says so.
- [ ] **Docs:** OME-1458 spec §4 and F4 amended; OME-1856 spec D15 reach note updated;
  `attempt_fold.py` reach comment updated; ledger outcome; mirror.
- [ ] **Gates:** the named lanes (ledger), ruff, ruff format, pyright on touched files.
