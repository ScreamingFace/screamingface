---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
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
