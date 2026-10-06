# OME-1445 — the archive-money test must not depend on the clock

## Problem

`packages/screamingface/tests/test_cache_saved_cost_submission.py` proves two money rules by
searching serialized output for text: `"0.5" not in json.dumps(payload)` (archive money is never
published, `OME-1251` D3) and `"2.000000" not in json.dumps(payload)` (spend and saving are never
summed, D5). The payload also holds `ran_at_local`, the run's completion time with microseconds, and
`result.to_dict()` holds its start and completion times. Any time containing the searched text fails
the test with nothing leaked. Seen in CI on #1149 (`…08:40:30.507912Z`).

## Decision (owner, 2026-10-01)

Check values, not text. Each assert collects the money-shaped leaves of the object (a `Decimal`, a
`float`, or a string that parses as a finite `Decimal`; never an `int`, a `bool` or a timestamp) and
asserts the forbidden amount is not among them. This keeps the original catch-all intent (the
amount may not appear under ANY key, including one added later) without matching a timestamp.

No regular expression is used: a string counts as money only if `Decimal()` parses it, which a
timestamp never does.

## Prior tests changed (approved, owner 2026-10-01)

`:98`, `:220`, `:221`: the same rule, now asserted on values. Nothing is weakened: each still fails
if the amount appears anywhere in the object, and it no longer fails when it does not.

## Out of scope

The other short-number text searches in the repo: each runs over fixed test data and cannot vary
between runs (scan recorded in the ledger).
