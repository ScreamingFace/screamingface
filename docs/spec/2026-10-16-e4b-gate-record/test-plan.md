# Test plan: E4b part 5 — gate record and verifier slot

Test ids are `<PREFIX>#<n>`, with the row number from each PRD's §7. Prefixes: `GR` gate record,
`VS` verifier slot, `GD` gate decision, `GA` gate API, `GS` gate display, `DC` docs.

## 1. Strategy

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| The majority branch depends on the fallback reply, so E4c cannot skip the call with no wire change (breaks ans:Q1) | H×H | unit, the same bytes over three contexts | GD#9, GD#10 |
| A weak majority is kept, or a strong one is replaced (wrong comparison, wrong number, wrong equality rule) | H×H | hand-computed oracles, boundary pairs | GD#2, GD#6–8, GD#16–17 |
| The gate abstain looks like a wrong answer or like a failure (breaks the epic and the E4c status rule) | H×M | unit + Case abstain rule | GD#3, GD#18, GR#2 |
| A fallback judge names a member that a weight or signal rule left out, and the evidence model fails with an undeclared error | H×M | unit, declared code | GD#21 |
| A later unit adds a case or a fixture file, and a CHAR row of an earlier unit turns red | H×M | fixed lists, never a glob (§6) | GR#1, GA#1, GS#1 |
| An existing evidence, spec, url4 or report changes bytes | H×M | CHAR on every fixture and case | GR#1, GD#1, GA#1, GS#1 |
| A gate reads an undeclared name and the run spends money before it fails | H×M | unit at construction | GA#8, GR#5 |
| A gated recipe does not rebuild from its url4, or a hand edit rebuilds as something else | H×M | round trip, hand-edit table | GA#12–14 |
| The fallback call does not run (breaks ans:Q1 "cost spent") or runs twice | H×M | Engine-world request count | GA#18 |
| The SDK and the Engine disagree on the words or the record | H×M | binding tests, contract fixture | GR#9, GR#14, GD#19 |
| The verifier slot accepts a value (breaks ans:Q4) | M×M | unit | VS#2, VS#3, VS#5 |
| Data text reaches the page unescaped | M×M | unit | GS#8 |
| A docs test breaks because a new bullet holds its token | M×M | unit | DC#5 |

## 2. TDD ground rules

- RED first. Run each new test and see it fail on the missing behavior, not on an import error. A
  new name may exist as a stub in the RED commit: a class or function that no existing path calls
  may raise `NotImplementedError`; a new keyword of an existing function defaults to the old
  behavior.
- A `CHAR` row pins today's behavior and passes before the change. It must stay true after it.
- A `PIN` row is an owner-approved edit of an existing golden, snapshot or pinned test; it is the
  smallest edit, and the build reports it (plan §6).
- How to regenerate a pinned snapshot:
  - A schema snapshot (`ET/data/combine_contract/schemas/*.json`, `ST/data/schemas/*.json`): the
    variable `UPDATE_SCHEMA_SNAPSHOT=1` writes only a MISSING file and never overwrites one
    (ET/schema_freeze_support.py:20-35, ST/_schema_freeze.py). So delete the pinned file, run the
    freeze test once with `UPDATE_SCHEMA_SNAPSHOT=1` (it writes the file and fails), then run it
    again without the variable.
  - The public surface snapshot (`ST/public_surface_snapshot.json`): run
    `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py` (it rewrites the file
    and fails), then run it again without the variable (ST/test_public_surface.py:29-34). Do not
    delete this file first.
- A CHAR row that names "every case" or "every fixture" uses a FIXED list from §6, never a glob
  and never a loop over the whole file, so a later unit cannot turn it red.
- A row with an `a` / `b` suffix (for example GA#12a, GA#12b) is built in two units. Each half is
  its own test function. The second unit appends its function (and appends to a builder table
  with a `|=` line); it never edits the test of the first unit. It counts as one row in §4.
- GREEN is the smallest change. Refactor on green only.
- One behavior for each test. The test name states the behavior.
- Every oracle is hand-computed in the PRD (fixture V of gate-decision §3, the GD-D9 contract
  numbers, the chip strings of gate-display §3), never copied from the code's output. A float
  that comes from a division is written as its exact Python repr in the PRD
  (`0.6666666666666666`, `0.6428571428571429`).
- Each user decision has a test that fails if the decision breaks:
  Q1 GD#2–5 (chooses), GD#9 (FB-I1), GA#18a, GA#18b (the fallback runs), GR#6 (records) ·
  Q2 GD#2, GD#6, GD#7 · Q3 GD#3, GD#4, GD#5, GA#2–4 · Q4 VS#1–6.
- No live provider call, no paid test, no eval run. All Engine runs use the Engine-world fake
  gateway (`ET/_signal_world.py`).

## 3. Lanes

| Lane | Where | What |
|---|---|---|
| Engine unit | `ET/test_combine_gate_words.py`, `ET/test_combine_gate.py` | spec parse, record model, the decision |
| Engine contract fixture | `ET/test_combine_evidence_contract_fixture.py` (pinned append) + `evidence_cases.json` | five gate cases |
| Engine world | `ET/test_combine_gate_run.py` | the SDK-compiled fixtures run offline |
| Schema freeze | `ET/test_wire_schema_freeze.py` (unchanged) + two pinned snapshots | spec v1, evidence v1 |
| SDK unit | `ST/test_gate_words.py`, `ST/test_gate_api.py`, `ST/test_gate_display.py`, `ST/test_gate_docs.py` | words, API, compile, rebuild, display, docs |
| SDK fixture drift guard | `ST/test_gate_contract_fixtures.py` | four new url4 fixtures |
| Binding | `ST/test_evidence_words.py`, `ST/unit/test_signal_key_conformance.py` (existing) + GA#16 | words and signal keys |
| Public surface | `ST/test_public_surface.py` (existing) + pinned snapshot | `sf.Gate`, `CombineGate`, `Vote` |

## 4. Aggregate

| PRD | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|
| [gate-record](prd/gate-record.md) | 5 / 4 / 6 | 17 |
| [verifier-slot](prd/verifier-slot.md) | 3 / 2 / 2 | 6 |
| [gate-decision](prd/gate-decision.md) | 8 / 6 / 10 | 21 |
| [gate-api](prd/gate-api.md) | 6 / 4 / 9 | 20 |
| [gate-display](prd/gate-display.md) | 5 / 1 / 5 | 12 |
| [docs](prd/docs.md) | 2 / 0 / 2 | 5 |
| **Total** | **29 / 17 / 34** | **81** |

## 5. Not tested

| Item | Why | Revisit when |
|---|---|---|
| A live judge or writer fallback | no live calls in this part; the judge and model paths are already tested live by earlier parts | a paid gate recipe is wanted |
| The skip of the fallback call | E4c (D1) | E4c |
| Calibration of the threshold (which number is "confident enough") | a research question, not correctness | a calibration report is planned |
| The verifier check | a later part (D5) | that part |

## 6. Fixed lists (taken on base `4e622af75`)

A CHAR row uses these lists as they are written here. It never reads a glob or the whole file,
because units 2–4 add five evidence cases and four url4 files to the same places.

**L32: the 32 evidence case names** of `ET/data/combine_contract/evidence_cases.json` (the SDK
`_EXPECTED_NAMES` set of `ST/test_combine_evidence_contract.py` as it is on base, before the unit 2
append). The test writes the names as a literal tuple; it does not import `_EXPECTED_NAMES`.

`argmax_cost_min`, `concat_collision`, `filter_none_pass`, `filter_pattern`,
`filter_signal_excluded`, `filter_threshold`, `judge_label`, `judge_scores`, `mean_weighted_value`,
`median_nearest`, `median_value`, `merge_abstain`, `merge_model_field`, `pick`, `pick_output`,
`pick_output_missing`, `projection`, `rank_by_judge`, `rank_by_signal`, `rank_cut_not_met`,
`rank_min_cost`, `rank_reduce_abstain`, `regex_no_match`, `set_normalized`, `vote_abstain`,
`vote_cost_signal`, `vote_field_signal`, `vote_judge_weights`, `vote_one_failed`, `vote_tie`,
`vote_weight_excluded`, `vote_weighted`.

**L43: the 43 url4 files** in `ET/data/combine_contract/` (no sub-folder):

`argmax_cost_candidate.url4`, `corrective_vote_candidate.url4`, `entropy_pick_min_candidate.url4`,
`filter_judge_candidate.url4`, `filter_pipeline_candidate.url4`, `judge_order_min_candidate.url4`,
`judge_vote_candidate.url4`, `logprob_entropy_shared_candidate.url4`,
`logprob_filter_mean_candidate.url4`, `logprob_filter_prob_candidate.url4`,
`logprob_pick_mean_candidate.url4`, `logprob_pick_sum_candidate.url4`,
`logprob_rank_mean_candidate.url4`, `logprob_samples_pick_candidate.url4`,
`logprob_steer_filter_candidate.url4`, `logprob_vote_prob_candidate.url4`,
`model_synthesizer_candidate.url4`, `quorum_judge_vote_candidate.url4`,
`quorum_vote_candidate.url4`, `recipe_s1.url4`, `recipe_s10.url4`, `recipe_s11_max.url4`,
`recipe_s12.url4`, `recipe_s13.url4`, `recipe_s14.url4`, `recipe_s15.url4`, `recipe_s16.url4`,
`recipe_s2.url4`, `recipe_s3.url4`, `recipe_s4.url4`, `recipe_s4_median.url4`, `recipe_s5.url4`,
`recipe_s5_pick_output.url4`, `recipe_s7.url4`, `recipe_s8.url4`, `recipe_s8_pick_output.url4`,
`recipe_s9.url4`, `samples_vote_candidate.url4`, `signal_vote_candidate.url4`,
`two_reducers_candidate.url4`, `verbalized_vote_candidate.url4`, `vote_candidate.url4`,
`weighted_median_confidence_candidate.url4`.
