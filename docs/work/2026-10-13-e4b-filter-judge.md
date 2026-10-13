---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-13
finished:
---

# e4b-filter-judge — Filter by judge score (`sf.Filter(..., judge=...)`)

## Intent

E4b part 1, unit 6 of 7 (PRD `docs/spec/2026-10-13-e4b-combine-extensions/prd/filter-judge.md`,
owner answers Q4, Q9, Q10, P6, P7). A benchmark author keeps only the members that a judge scores
at or over a threshold, and a writer model writes the final answer from them (the threshold
variant of S10). The SDK pairs `where=sf.signal("score:judge") <op> x` with
`judge=sf.Judge(..., returns="scores")`, the same rule as `sf.Vote`, and compiles one judge call.
The Engine does not change. CHAR tests pin its `filter@1` read of `score:judge`.

## Planned changes

- `packages/screamingface/src/screamingface/selection.py` — `Filter.judge`, `_check_filter_judge`,
  judge `signal_calls` in `_plan`, `_rebuild` with the judge call, render, block options.
- `packages/screamingface/src/screamingface/blocks.py` — `_OPS["filter"]` takes `judge`.
- `packages/screamingface/tests/test_filter_judge.py` (new) — FJ#2-5, FJ#11.
- `packages/screamingface/tests/test_filter_judge_url4_fixture.py` (new) — fixture builder and drift guard.
- `apps/screamingface-engine/tests/unit/test_combine_filter_judge.py` (new) — FJ#1, FJ#6-10 (CHAR).
- `apps/screamingface-engine/tests/unit/test_sdk_filter_judge_contract.py` (new) — FJ#12.
- `apps/screamingface-engine/tests/unit/data/combine_contract/filter_judge_candidate.url4` (new, generated).
- PINNED (owner approval at the end): `packages/screamingface/tests/test_filter.py` (the one
  `score:judge` message regex), `packages/screamingface/tests/public_surface_snapshot.json` (Filter entry).
- `packages/screamingface/README.md` (Filter section, Combine recipes S10 row),
  `packages/screamingface/CHANGELOG.md` (one Features bullet).

## Test plan

- CHAR first (engine, pass on the first run): FJ#1 keep at >= 7 incl. the boundary 7; FJ#6 evidence
  (signal values, pass marks, `signal`, `judge: null`, `presentation_order: author`); FJ#7 no pass →
  abstain `no_votes`; FJ#8 bad reply → `judge_reply_invalid`, permanent, not echoed; FJ#9 quorum
  panel: missing member dropped, judge scores only the panel; FJ#10 `<` keeps low scores.
- RED then GREEN (SDK): FJ#2 compile adds one judge call and `signals: {judge: '$judge_1'}`; FJ#3
  `score:judge` without `judge=` is refused and names `judge=`; FJ#4 `judge=` without a `score:judge`
  comparison is refused; FJ#5 a label or `order="min"` judge is refused; FJ#11 url4 round trip
  (named, block, quorum, tampered).
- RED then GREEN (integration): FJ#12 the SDK-compiled fixture runs in the engine world; the writer
  gets `{"input", "selected"}` with members 1 and 3 only.
- Invariant protected: a Filter without `judge` keeps its compiled bytes.

## Acceptance

- FJ#1-12 green; the existing Filter, Vote-judge, Rank and fixture tests green with no regenerate.
- `run_gates.py screamingface-engine` and `repo` green; `screamingface` green except the
  append-only check, which lists only the two pinned files waiting for owner approval.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** commit A adds the ledger, `ST/test_filter_judge.py`,
  `ST/test_filter_judge_url4_fixture.py`, `ET/test_combine_filter_judge.py`,
  `ET/test_sdk_filter_judge_contract.py`, and the signature-only stub in `S/selection.py`.
  The fixture data file and the pinned edits come in commit B.
- **Commits:** commit A (RED), sha to be filled after commit.
- **RED run (commit A, SDK focused and full suite):** 9 failed, 4194 passed, 32 skipped. The red
  tests are the 8 FJ tests and the public surface snapshot (expected, pinned in commit B).
- **RED reasons (commit A):**
  - FJ#2: fails at `sf.Filter(where=score:judge, judge=...)` construction with the old refusal
    "Filter cannot read sf.signal('score:judge')...". The spec expected assertion (1).
  - FJ#3: "Regex pattern did not match", actual "Filter cannot read sf.signal('score:judge')...".
  - FJ#4: "DID NOT RAISE ValueError" for `sf.signal("field:confidence") >= 0.6`.
  - FJ#5: "Regex pattern did not match", actual "Filter cannot read sf.signal('score:judge')...".
  - FJ#11 (plain, quorum): fails at Filter construction, as FJ#2. The block and repr test fails
    with "sf.Reduce('filter') does not take option 'judge'".
  - FJ#12 (engine): `FileNotFoundError` for `filter_judge_candidate.url4`, as the spec expected.
  - Drift guard: "combine_contract/filter_judge_candidate.url4 is missing", as the spec expected.
  - CHAR (pass): FJ#1, FJ#6, FJ#7, FJ#8 (3 cases), FJ#9, FJ#10: 8 passed.
- **Gates (commit A):** `ruff check`, `ruff format --check` and `pyright` pass in both stacks.
  pytest is red only for the expected rows above.
- **Deviations:**
  - Step 0 checks all matched the spec (unit 1 `input` envelope, unit 5 `order`,
    `_refuse_min_order_judge` in `reducer.py`, the order message, `judge_from_signals`, the
    repr). Step 0.2 test is `test_filter_pipeline_writer_sees_the_input_and_kept_members`.
  - The stub keeps the old `_check_filter_where` refusal (the spec says to keep it until GREEN).
    So a `score:judge` judge Filter fails at construction, not at its first assertion (FJ#2, FJ#11).
  - `F` became the function `_filter_by_judge()`. A module-level construction would fail at import
    and error the whole file.
  - FJ#11 block, repr and tampered checks are in their own test
    (`test_filter_block_and_repr_rebuild_the_judge_filter`), because the round-trip test hit ruff
    PLR0915. The assertions are the same.
