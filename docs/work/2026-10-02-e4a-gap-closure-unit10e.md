---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 10E -- Engine signals: rank by signal, argmax, filter, cut_not_met

## Intent

Fold the engine part of SR#5-8, SR#12, FL#1-5, FL#10 and AB#3 on top of the unit 1 core and the
unit 8E and 9E operators. A top-k cut that cannot be met abstains with `cut_not_met`. `top_k@1`
gains an `order` arg. New operators rank members by a named signal (`by_signal@1`,
`best_holder@1`) and filter them by a signal threshold or a regex (`filter@1`, `kept@1`). The
`Reducer` literal gains `filter`, and `pick` may run without an extract.
Branch `e4a-rank-concat-engine` is rebased onto `e4a-pick-merge-engine` (tip `9917220a0`).

## Planned changes

- Commit B: repair the two status rows in `test_combine_selection.py` (S1), no RED.
- Commit C: AB#3, `top_k@1` raises `NoVotes(reason="cut_not_met")`.
- Commit D: `Reducer` gains `filter`; `REDUCER_RULES` loosens `pick` and adds `filter` (F2).
- Commit E: `top_k@1` takes the optional `order` arg (F10).
- Commit F: `signals.py` with `by_signal@1` and `best_holder@1` (F3-F5).
- Commit G: `extract.py` public regex helpers, `filter@1` and `kept@1` (F6-F9).
- Commit H: guards (hash-seed replay, engine world, catalog).
- Commit I: results.

## Test plan

Rows 1-22 of the spec section 3. Rows with no RED by design: Commit B; rows 20-22 (guards).

## Notes

### Rebase (spec section 2.0)

`git rebase --onto e4a-pick-merge-engine 50e820f53 e4a-rank-concat-engine` replayed 5 commits with
no textual conflict (`builtins.py` applied as it was). The parent then moved from `9917220a0` to
`7c6685790` (three review-fix commits, no behavior change); `git rebase --onto
e4a-pick-merge-engine 9917220a0 e4a-rank-concat-engine` replayed 11 commits, again with no conflict.

Red set right after the first rebase: exactly S1-S3 (6 tests: two status rows in
`test_combine_selection.py`, the two "fewer than k" tests, and the two `top_k@1` goldens). S4 is a
docstring.

- F1: no textual conflict. Semantic breaks S1 (commit B), S2-S4 (commit C).
- F2: `pick` extract is optional; `filter` is a new reducer and rule. Errata: the old P3 line
  "REDUCER_RULES does not change in units 8-10". SDK flag: `S/reducer.py` `_ReducerName` lacks
  `"filter"` until 10S adds it.
  Review erratum: with `pick` extract optional, a hand-written `values@1` + `by_field@1` spec
  without an extract is accepted. Its `equals` form abstains with `no_votes` (before:
  `combine_spec_invalid`); its `max` and `min` forms still fail with `combine_spec_invalid`. The SDK
  always writes the extract for a field pick. Pinned in `test_combine_signal_reducers.py`.
- F3: the select step's `order` decides the pick; `by_signal@1`'s `order` is what `signal_read`
  reports. The engine does not cross-check the two. Errata (INVARIANT for the SDK: same value).
  Pinned by a test: `by_signal` max + `best_holder` min picks the min holder, and the evidence says
  max. A cross-check needs a core hook (follow-up).
- F4: `by_signal@1` scores voters only. A member that failed keeps its number in the row, and has no
  score.
- F5: missing signal gives `no_votes`; a short top-k cut gives `cut_not_met`; `best_holder@1` with
  empty scores is `SpecInvalid`.
- F6: `filter@1` returns one 1 or 0 mark per voter in `Reduction.scores`; evidence
  `members[].score` shows 1.0 or 0.0 for voters and None for members that failed. Errata: filter
  evidence semantics.
- F7: `value` is a finite number, or a bool with `eq` only. Errata and SDK note (10S):
  `sf.signal("field:x") == True` also passes for a numeric 1, because signals hold floats.
- F8/F9: a pattern predicate reads the original output through the regex@1 rule. `extract.py` gains
  `check_regex_pattern` and `regex_finds` and a private `_regex_window`; the regex@1 goldens are the
  guard and did not change.
- F10: `top_k@1` gains the optional `order`; every old golden keeps its bytes. The catalog test is
  updated in place.
- F11: `by_signal@1` takes exactly `{key, order}`, `best_holder@1` exactly `{order}`.
  `by_signal@1`'s `check_args` also checks `is_signal_key`, so a bad key fails at the operator and
  the message never holds the key.
- F12: accounting keys work through the `signal_read` hooks. SDK flag (9S/10S): extend unit 7's
  `accounting_signal(reducer)` seam to `by_signal` and filter keys, or those Cases fail with
  `combine_spec_invalid`.
- F13/F14: tests only (rows 18 and 11).

## Outcome

Commits: A ledger; B repair (S1); C rows 1 (AB#3); D rows 2-4; E rows 5-6; F rows 7-12; G rows
13-19; H rows 20-22; I this record.

RED seen: C (reason `no_votes`, and the two goldens), D (`filter` not in `Reducer`, `pick`
requires extract), E (min order, 5 tests: the 3 bad-order args cases passed at once, see below),
F (`combine_operator_unknown`; goldens `LookupError`), G (same). I wrote no stubs: an absent
operator is a failing assertion for each row.

Rows without RED by design: commit B; rows 20-22 (guards: hash-seed replay, the engine world and
the catalog passed at once; every world signal was a number, so no adapter defect); the
bad-`order` rows of row 5 and the three bad-order goldens (the old `top_k@1` already refused any
extra key).

Deviations from the spec text:

- Row 1 (AB#3), judge case: the context holds two members, so the scores are `[1.0, 2.0]`, not
  `[1.0, 2.0, None]`. The three-member field case asserts `[1.0, 2.0, None]`.
- Commit G was amended once, before any push: `_THRESHOLD_KEYS` was a set and the plugin
  mutable-state test failed, so it is a `frozenset`.
- `kept@1` checks every mark in the reduction, also marks of members that are not read.

Gates (base `e4a-pick-merge-engine`):

- engine, `--skip-append-only`: ruff check, ruff format, pyright, check_layering, pytest with
  coverage all green. ALL GATES GREEN.
- engine, with append-only: ALL GATES GREEN. No append-only offenders.
- screamingface (SDK): not run, no SDK file changed.
- repo: ALL GATES GREEN.
