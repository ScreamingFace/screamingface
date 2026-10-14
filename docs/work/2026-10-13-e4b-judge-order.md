---
ticket: OME-1601
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-13
finished: 2026-10-13
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

- **Actual files:** As planned. Code: `judge.py`, `blocks.py`, `reducer.py`, `selection.py`. Tests and
  data: the four new test files, the fixture `judge_order_min_candidate.url4`, and the snapshot
  `public_surface_snapshot.json` (pinned edit). Docs: `README.md` and `CHANGELOG.md`.
- **Commits:** `4a54f1d06` test(e4b): RED for E4b unit 5 judge-order (A: RED tests and stubs);
  `529b039e0` feat(screamingface): sf.Judge(..., order="min") picks the lowest judge score (B: GREEN);
  the docs commit that adds this Outcome (C).
- **Gates:**
  - `run_gates.py screamingface --base e4b-weighted-median`: append-only FAILED with one offender,
    `tests/public_surface_snapshot.json` (approved pinned edit, no manifest yet).
  - `run_gates.py screamingface --base e4b-weighted-median --skip-append-only`: ALL GATES GREEN
    (ruff check, ruff format, pyright, pytest with coverage, notebooks, uv build, distribution).
  - `run_gates.py repo --base e4b-weighted-median`: ALL GATES GREEN, append-only check ON.
  - Focused engine tests (`test_combine_judge_order.py`, `test_sdk_judge_order_contracts.py` and
    the engine neighbors): 62 passed. The `screamingface-engine` gate was not run in this pass.
- **Pinned edit for owner approval:** `packages/screamingface/tests/public_surface_snapshot.json`
  base_blob e11797349144ce62db42617293d6bbdf7019fd56 → approved_blob 49c4b7bfeff79c7365ce3fdb753c87d0eb01f9ab
  (2 changes: the Judge `__init__` gains `order`; the member `"order": "field"` is added).
- **Deviations:**
  - JO#12 test fix in `test_sdk_judge_order_contracts.py`: the system prompt separator is U+2028,
    not a space. The RED test had the wrong character. Commit B holds the fix.
  - No `S11 min` row existed in the README table. A row with inline code was added, as the
    `S4, median form` row does. It names no new recipe, so no builder or fixture was added.
  - The `screamingface-engine` gate was not run, because the run named only `screamingface` and `repo`.
