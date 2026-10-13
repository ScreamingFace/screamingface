---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-13
finished:
---

# e4b-judge-order — sf.Judge(..., order="min"): the lowest judge score wins

## Intent

A benchmark author can use a rubric where a lower score is better (an error count, a risk score).
`sf.Judge(model, returns="scores", rubric=R, order="min")` tells the judge "A lower number means a
better answer" (first line `judge-template@1 returns=scores order=min`). The Fusion answer is the
original text of the member with the lowest score (`select: best_holder@1 {"order":"min"}`).
The change is SDK only. A judge without an order keeps its url4 bytes. Rank and Vote refuse a
min-order judge (P6).
Spec: docs/spec/2026-10-13-e4b-combine-extensions/prd/judge-order.md (ans:Q11, P6, N1).
Unit 5 of docs/plan/2026-10-13-e4b-combine-extensions.md.

## Planned changes

- `packages/screamingface/src/screamingface/judge.py` — `order` field and keyword; template, format
  and step tables keyed by `(returns, order)`; `_parts`, `judge_from_signals`, `_shape_of`,
  `outputs_form_prompt`, `panel_judge_signal`, `_with_overrides`, `__repr__`, `_key`.
- `packages/screamingface/src/screamingface/blocks.py` — the `judge` op takes an optional `order`.
- `packages/screamingface/src/screamingface/reducer.py` — `_refuse_min_order_judge`; Vote's judge
  check calls it.
- `packages/screamingface/src/screamingface/selection.py` — Rank's source check calls it.
- New tests: `packages/screamingface/tests/test_judge_order.py`,
  `packages/screamingface/tests/test_judge_order_url4_contract_fixtures.py`,
  `apps/screamingface-engine/tests/unit/test_combine_judge_order.py`,
  `apps/screamingface-engine/tests/unit/test_sdk_judge_order_contracts.py`.
- New fixture: `apps/screamingface-engine/tests/unit/data/combine_contract/judge_order_min_candidate.url4`.
- Approved pinned edit: `packages/screamingface/tests/public_surface_snapshot.json` (Judge gains `order`).
- Docs: `packages/screamingface/README.md` (judge section, Combine recipes S11 min row),
  `packages/screamingface/CHANGELOG.md`.

## Test plan

- CHAR first: JO#1 (engine `scores@1` plus `best_holder@1 {"order":"min"}` picks the lowest member),
  JO#2 (a judge without an order still compiles `max_score@1` and the old template).
- RED then GREEN: JO#3 compile to `best_holder@1 min`; JO#4 the judge is told lower is better;
  JO#5 a label judge refuses `order="min"`; JO#6 an unknown order is refused; JO#7 Rank and Vote
  (and the shared check for Filter) refuse a min judge; JO#8 url4 round trip and the judge block;
  JO#9 a tie at the lowest score goes to the first member; JO#10 panel first line; JO#11 key and
  repr; JO#12 engine run of the SDK fixture returns the lowest member's text with full evidence;
  JO#13 public surface lists `order`.
- Invariant protected: the bytes of every judge without an order do not change.

## Acceptance

- JO#1–JO#13 green; the neighbor judge, rank, vote, block, fixture and doc-golden tests green with
  no edit.
- `run_gates.py repo` and `run_gates.py screamingface-engine` green vs `e4b-weighted-median`.
- `run_gates.py screamingface` green except the append-only offender
  `tests/public_surface_snapshot.json`, which waits for the owner's approval manifest.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message> (A: RED tests + stubs; B: GREEN; C: docs)
- **Gates:** <run_gates.py result lines for screamingface (with and without --skip-append-only), repo, screamingface-engine>
- **Pinned edit for owner approval:** `packages/screamingface/tests/public_surface_snapshot.json`
  base_blob <git rev-parse e4b-weighted-median:...> → approved_blob <git hash-object ...>
- **Deviations:** <anything that differed from the plan, or "none">
