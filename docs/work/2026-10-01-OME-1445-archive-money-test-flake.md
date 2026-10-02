---
ticket: OME-1445
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# archive-money-test-flake — stop the SDK archive-money test failing on the clock

## Intent

`test_archive_money_never_reaches_the_result_or_the_board` (added in #1075, `OME-1326`) protects
`OME-1251` D3: archive-matched money is never published, under any field. It checks this with
`"0.5" not in json.dumps(payload)` and the same over `result.to_dict()`. Both also carry the run's
timestamp (`ran_at_local` is `completed_at`, with microseconds), so whenever that time contains
`0.5` the test fails with no money leaked: CI on #1149, `ran_at_local` `…08:40:30.507912Z`. The same
shape sits at `:98` (`"2.000000" not in json.dumps(payload)`, the never-summed rule), far less
likely to trip. Replace the text searches with checks on VALUES, so a timestamp can never match.

Repo-wide scan (2026-10-01): every other `"<short number>" not in <serialized>` assert in the repo
searches output built only from fixed test data, so none can fail on the clock. This unit touches
only this file.

## Planned changes

- `packages/screamingface/tests/test_cache_saved_cost_submission.py`:
  - `_CachedReplayTransport` gains an optional `completed_at` so a test can pin the run's clock;
  - a `_money_values(obj)` helper collecting every money-shaped leaf (Decimal, float, or a string
    that parses as a finite Decimal; never int or bool, never a timestamp);
  - `:98`, `:220`, `:221` assert on those values, not on serialized text (approved prior-test change);
  - a new regression test: the archive case run with `completed_at` = `08:40:30.507912Z`.
- `docs/tasks/2026-10-01-OME-1445-archive-money-test-flake.md` (mirror).

## Test plan

- RED: the regression test, written against the CURRENT text-search assertion, fails
  deterministically on the pinned clock (the flake reproduced).
- GREEN: with value checks, it passes; the original test and `:98` still pass.
- Mutation: make the submission leak the archive amount under a new key; the value check fails.

## Acceptance

- the three asserts check values; no substring search over serialized output remains in the file
- the pinned-clock regression passes; the leak mutation is caught
- `run_gates.py screamingface` green (append-only flags only the three approved lines)

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `packages/screamingface/tests/test_cache_saved_cost_submission.py`
  (`_CachedReplayTransport` gains an optional `finished`, which pins the run's start one second
  earlier and its completion; `_leaves`, `_as_money`, `_money_values`, `_assert_no_money`; the
  three asserts; the regression test), plus this ledger, the spec, the plan and the mirror.
- **Commits:** one, `Refs: OME-1445`.
- **Gates:** `run_gates.py screamingface --base origin/main --skip-append-only` ALL GATES GREEN
  (ruff, format, pyright, pytest with 95% floor, notebooks, build, distribution); suite 2104 passed,
  26 skipped, coverage 96%. Without the skip, append-only flags exactly old lines 98, 220, 221 (the
  approved asserts) and 175 (the transport's `__init__`, which gained a defaulted parameter).
- **RED/GREEN:** the regression test failed on the pinned clock with today's text search
  (`assert '0.5' not in '{"version":...'`), with no money leaked; it passes with the value check.
- **Mutation:** `_submission` temporarily made to add `"0.500000"` and `"2.000000"` under new keys:
  all three money tests failed (`0.500 reached the object`, `2.000000 reached the object`). Reverted.
- **Deviations:** the transport parameter is `finished` and pins `started_at` too, because a result
  refuses a completion that precedes its start (found at RED). No regular expression is used: a
  string counts as money only if `Decimal()` parses it.
