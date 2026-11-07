# Test plan: E4b part 6 — signal sums and the abstain band

Test ids are `<PREFIX>#<n>`, with the row number from each PRD's §7. Prefixes: `SM` signal sum
(Engine), `SA` sum API (SDK), `AB` abstain band (words, decision, record), `BA` band API (SDK),
`SD` sum and band display, `DC` docs.

## 1. Strategy

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| A sum value is wrong (float rounding, order of terms, a missing component read as zero) | H×H | hand-computed exact oracles, both term orders | SM#4, SM#5, SM#6 |
| A number on the edge of the band takes the wrong branch (open vs closed interval) | H×H | boundary triple with adjacent floats | AB#5 |
| The band branch reads a fallback reply, so E4c cannot skip the call with no wire change | H×H | the same bytes with and without the reply | AB#7 |
| The band changes the part 5 comparison outside the band | H×H | the part 5 evidence plus one key | AB#6, AB#17 |
| A sum of a raw logprob or entropy becomes a vote weight (breaks part 3 ans:Q11) | H×M | unit at construction | SA#6 |
| A sum reads an undeclared name or another sum, and the run spends money before it fails | H×M | unit at construction, and the Engine spec check | SA#4, SA#5, SM#3 |
| An existing spec, evidence, url4, gate record or report changes bytes | H×M | CHAR on fixed lists | SM#1, SA#1, AB#1, BA#1, SD#1 |
| A later unit adds a case or a fixture, and a CHAR row of an earlier unit turns red | H×M | fixed lists, never a glob (§6) | SM#1, AB#1, SD#1 |
| The SDK and the Engine disagree on the words or the record | H×M | binding tests, contract fixture | AB#14, AB#16, SM#12 |
| A sum or a band does not rebuild from its url4, or a hand edit rebuilds as something else | H×M | round trip, hand-edit table | SA#10, SA#11, BA#5, BA#6 |
| The report shows a band Case as "not run", or the summary crashes on a large mean | M×M | unit | SD#4, SD#6, SD#9 |
| A docs test breaks because the new bullet or heading holds a counted token | M×M | unit | DC#1, DC#5 |

## 2. TDD ground rules

- RED first. Run each new test and see it fail on the missing behavior, not on an import error. A
  new name may exist as a stub in the RED commit: a class or function that no existing path calls
  may raise `NotImplementedError`; a new keyword of an existing function defaults to the old
  behavior.
- A `CHAR` row pins today's behavior and passes before the change. It must stay true after it.
- A `PIN` row is an owner-approved edit of an existing golden, snapshot or pinned test; it is the
  smallest edit, and the build reports it (plan §6). The build never writes
  `.claude/test-change-approvals/`.
- How to regenerate a pinned snapshot:
  - A schema snapshot (`ET/data/combine_contract/schemas/*.json`, `ST/data/schemas/*.json`): the
    variable `UPDATE_SCHEMA_SNAPSHOT=1` writes only a MISSING file and never overwrites one
    (ET/schema_freeze_support.py, ST/_schema_freeze.py). So delete the pinned file, run the freeze
    test once with `UPDATE_SCHEMA_SNAPSHOT=1` (it writes the file and fails), then run it again
    without the variable.
  - The public surface snapshot (`ST/public_surface_snapshot.json`): run
    `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py` (it rewrites the file
    and fails), then run it again without the variable. Do not delete this file first.
  - `ET/data/combine_contract/evidence_cases.json`: run
    `ET/test_combine_evidence_contract_fixture.py` as a script (`write_fixture`), then check that
    only the new case was added (`git diff` shows one new key and no changed line of an old case).
- A CHAR row that names "every case" or "every fixture" uses a FIXED list from §6, never a glob and
  never a loop over the whole file, so a later unit cannot turn it red.
- GREEN is the smallest change. Refactor on green only.
- One behavior for each test. The test name states the behavior.
- Every oracle is hand-computed in the PRD (the exact sums with `fractions.Fraction`, the means of
  the band fixtures, the chip strings), never copied from the code's output. A float that comes from
  a division or a rounding is written as its exact Python repr (`0.6666666666666666`,
  `3.1666666666666665`, `0.31`).
- Each user decision has a test that fails if the decision breaks:
  Q1 SM#6 (each member gets the sum), SM#7 (Pick, Rank, Filter), SM#8 (weights), SM#9 (gate
  chosen and mean), SM#10 (recorded), SA#7, SA#10 · Q2 AB#4 (inside: abstain with `in_band`), AB#6 (outside: as
  today), AB#4 and AB#12 (recorded), BA#2, BA#8.
- No live provider call, no paid test, no eval run. All Engine runs use the Engine-world fake
  gateway (`ET/_signal_world.py`).

## 3. Lanes

| Lane | Where | What |
|---|---|---|
| Engine unit | `ET/test_combine_signal_sum.py`, `ET/test_combine_signal_sum_words.py`, `ET/test_combine_band.py` | spec parse, sum value, band decision, record model |
| Engine contract fixture | `ET/test_combine_evidence_contract_fixture.py` (insert before `def canonical_evidence`) + `evidence_cases.json` (pinned) | `pick_sum_min`, `vote_gate_band` |
| Engine world | `ET/test_combine_sum_run.py` | the SDK-compiled fixtures run offline |
| Schema freeze | `ET/test_wire_schema_freeze.py` (unchanged) + pinned snapshots | spec v1, evidence v1 |
| SDK unit | `ST/test_signal_sum_api.py`, `ST/test_band_words.py`, `ST/test_band_api.py`, `ST/test_sum_band_display.py`, `ST/test_sum_band_docs.py` | API, compile, rebuild, words, display, docs |
| SDK fixture drift guard | `ST/test_sum_contract_fixtures.py` | two new url4 fixtures |
| Binding | `ST/test_evidence_words.py`, `ST/test_gate_words.py` (pinned) + AB#14 | the words of both sides |
| Public surface | `ST/test_public_surface.py` (existing) + pinned snapshot | `Sum`, `CombineGate`, `Gate` |

## 4. Aggregate

| PRD | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|
| [signal-sum](prd/signal-sum.md) | 5 / 2 / 6 | 14 |
| [sum-api](prd/sum-api.md) | 5 / 4 / 5 | 14 |
| [abstain-band](prd/abstain-band.md) | 4 / 3 / 8 | 18 |
| [band-api](prd/band-api.md) | 4 / 2 / 3 | 9 |
| [sum-band-display](prd/sum-band-display.md) | 5 / 1 / 4 | 10 |
| [docs](prd/docs.md) | 2 / 0 / 2 | 5 |
| **Total** | **25 / 12 / 28** | **70** |

## 5. Not tested

| Item | Why | Revisit when |
|---|---|---|
| A live run of a sum or a band | no live calls in this part; the verbalized and gate paths are already tested by earlier parts | a paid CodeX-Verify recipe is wanted |
| Calibration of the coefficients or the band | a research question, not correctness | a calibration report is planned |
| The skip of the fallback call on the band branch | E4c | E4c |
| A sum with a `consistency@N` component | part 7 is built in parallel | after the part 7 rebase (one CHAR row then) |

## 6. Fixed lists (taken on base `633fec3a1`)

A CHAR row uses these lists as they are written here. It never reads a glob or the whole file,
because units 1–5 add two evidence cases and two url4 files to the same places.

**L37: the 37 evidence case names** of `ET/data/combine_contract/evidence_cases.json`. The test
writes the names as a literal tuple; it does not import `_EXPECTED_NAMES`.

`argmax_cost_min`, `concat_collision`, `filter_none_pass`, `filter_pattern`,
`filter_signal_excluded`, `filter_threshold`, `judge_label`, `judge_scores`, `mean_weighted_value`,
`median_nearest`, `median_value`, `merge_abstain`, `merge_model_field`, `pick`, `pick_output`,
`pick_output_missing`, `projection`, `rank_by_judge`, `rank_by_signal`, `rank_cut_not_met`,
`rank_min_cost`, `rank_reduce_abstain`, `regex_no_match`, `set_normalized`, `vote_abstain`,
`vote_cost_signal`, `vote_field_signal`, `vote_gate_abstain`, `vote_gate_judge`,
`vote_gate_majority`, `vote_gate_not_run`, `vote_gate_writer`, `vote_judge_weights`,
`vote_one_failed`, `vote_tie`, `vote_weight_excluded`, `vote_weighted`.

**L47: the 47 url4 files** in `ET/data/combine_contract/` (no sub-folder):

`argmax_cost_candidate.url4`, `corrective_vote_candidate.url4`, `entropy_pick_min_candidate.url4`,
`filter_judge_candidate.url4`, `filter_pipeline_candidate.url4`,
`gate_abstain_vote_candidate.url4`, `gate_judge_vote_candidate.url4`,
`gate_verbalized_vote_candidate.url4`, `gate_writer_vote_candidate.url4`,
`judge_order_min_candidate.url4`, `judge_vote_candidate.url4`,
`logprob_entropy_shared_candidate.url4`, `logprob_filter_mean_candidate.url4`,
`logprob_filter_prob_candidate.url4`, `logprob_pick_mean_candidate.url4`,
`logprob_pick_sum_candidate.url4`, `logprob_rank_mean_candidate.url4`,
`logprob_samples_pick_candidate.url4`, `logprob_steer_filter_candidate.url4`,
`logprob_vote_prob_candidate.url4`, `model_synthesizer_candidate.url4`,
`quorum_judge_vote_candidate.url4`, `quorum_vote_candidate.url4`, `recipe_s1.url4`,
`recipe_s10.url4`, `recipe_s11_max.url4`, `recipe_s12.url4`, `recipe_s13.url4`, `recipe_s14.url4`,
`recipe_s15.url4`, `recipe_s16.url4`, `recipe_s2.url4`, `recipe_s3.url4`, `recipe_s4.url4`,
`recipe_s4_median.url4`, `recipe_s5.url4`, `recipe_s5_pick_output.url4`, `recipe_s7.url4`,
`recipe_s8.url4`, `recipe_s8_pick_output.url4`, `recipe_s9.url4`, `samples_vote_candidate.url4`,
`signal_vote_candidate.url4`, `two_reducers_candidate.url4`, `verbalized_vote_candidate.url4`,
`vote_candidate.url4`, `weighted_median_confidence_candidate.url4`.

The new names of this part: cases `pick_sum_min` (unit 1) and `vote_gate_band` (unit 4); url4
files `sum_pick_candidate.url4` (unit 2) and `gate_band_vote_candidate.url4` (unit 5). No name
starts with `recipe_` (the README recipe tests read that prefix).
