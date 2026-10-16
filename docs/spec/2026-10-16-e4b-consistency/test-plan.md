# Test plan: E4b part 7 — consistency@N

Test ids are `<PREFIX>#<n>`, with the row number from each PRD's §7. Prefixes: `CR` consistency
record, `CV` consistency value, `CA` consistency API and compile, `CB` consistency rebuild, `CD`
consistency display, `DC` docs.

## 1. Strategy

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| A failed extra call fails the Case (breaks ans:Q4) | H×H | Engine-world run with a gateway 400 on one sample | CA#7, CV#4 |
| The value uses the wrong denominator (all n, or the member's own answer) or the wrong match (no normalize) | H×H | hand-computed fixtures V and W, exact floats | CV#2, CV#3, CV#9 |
| The extra calls do not use distinct seeds or the stated temperature, or they change the member's other params (breaks ans:Q3) | H×H | exact url4 params, exact gateway bodies | CA#4, CA#7 |
| A sample call shares a fingerprint with a member call, so the member's accounting or logprob numbers turn unknown | H×M | fingerprint sets | CA#11 |
| The samples vote or join the panel | H×M | unit, all samples disagree | CV#8 |
| A model without `seed` or `temperature` spends money before it fails | H×M | preflight unit | CA#10 |
| An existing spec, evidence, url4 or report changes bytes | H×M | CHAR on fixed lists | CR#1, CV#1, CA#1, CB#1, CD#1 |
| A later unit adds a fixture or a case and a CHAR row of an earlier unit turns red | H×M | fixed lists, never a glob (§6) | CR#1, CA#1, CB#1, CD#1 |
| The url4 of a consistency recipe does not rebuild, or a hand edit rebuilds as something else | H×M | round trip, hand-edit table | CB#2, CB#5 |
| The SDK and the Engine disagree on the record | H×M | a separate contract fixture file read on both sides | CV#13, CV#14 |
| The parallel part 6 and this part break each other's docs or snapshots | M×M | order checks, not fixed indexes; contracts C8 | DC#2, DC#5 |
| Data text reaches the page unescaped | M×L | the chip and the note hold only numbers and the checked name | CD#2, CD#3 |

## 2. TDD ground rules

- RED first. Run each new test and see it fail on the missing behavior, not on an import error. A
  new name may exist as a stub in the RED commit: a class or function that no existing path calls
  may raise `NotImplementedError`; a new keyword of an existing function defaults to the old
  behavior.
- A `CHAR` row pins today's behavior and passes before the change. It must stay true after it.
- A `PIN` row is an owner-approved edit of an existing snapshot; it is the smallest edit, and the
  build reports it (plan §6). The build never writes `.claude/test-change-approvals/`.
- How to regenerate a pinned snapshot:
  - A schema snapshot (`ET/data/combine_contract/schemas/*.json`): `UPDATE_SCHEMA_SNAPSHOT=1`
    writes only a MISSING file and never overwrites one (ET/schema_freeze_support.py:20-35). So
    delete the pinned file, run `ET/test_wire_schema_freeze.py` once with
    `UPDATE_SCHEMA_SNAPSHOT=1` (it writes the file and fails), then run it again without the
    variable.
  - The public surface snapshot (`ST/public_surface_snapshot.json`): run
    `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py` (it rewrites the file
    and fails), then run it again without the variable (ST/test_public_surface.py:29-34). Do not
    delete this file first.
- A new contract data file (`consistency_evidence_cases.json`, the two `consistency_*.url4`
  files) is written by its own `write_fixture()` once, then checked by a plain run. A missing file
  FAILS; it is never skipped.
- An error row that lists a message asserts that exact text (`str(exc) == text`), never "one of
  a set". A wrong expected text found at the first run is corrected once, before the unit commit,
  and recorded in the ledger and in overview §10.
- A CHAR row that names "every case" or "every fixture" uses a FIXED list from §6, never a glob
  and never a loop over a whole file, so a later unit (or part 6) cannot turn it red.
- GREEN is the smallest change. Refactor on green only. One behavior for each test; the test name
  states the behavior.
- Every oracle is hand-computed in the PRD (fixtures V and W of consistency-value §3, the seeds of
  erd §2, the chip strings of consistency-display §3), never copied from the code's output. A float
  from a division is written as its exact Python repr (`0.6666666666666666`).
- Each owner decision has a test that fails if the decision breaks:
  Q3 CA#2 (`temperature` default 1.0), CA#4 (distinct seeds, the stated temperature), CA#4 row
  CA-7 (the member's other params unchanged), CA#7 (the gateway bodies) ·
  Q4 CV#2 (matched over succeeded), CV#2 and CR#7 (the failed count is recorded), CV#4 (all
  failed → missing → the rule excludes the member), CA#7 (the Case does not fail).
- No live provider call, no paid test, no eval run. All Engine runs use a mocked gateway
  (`httpx.MockTransport`). No test goes under a `paid` folder or marker.

## 3. Lanes

| Lane | Where | What |
|---|---|---|
| Engine unit | `ET/test_combine_consistency_words.py`, `ET/test_combine_consistency.py` | spec and context parse, the record model, the value |
| Engine contract fixture | `ET/test_combine_consistency_contract.py` + `consistency_evidence_cases.json` | three scenarios |
| Engine world | `ET/test_combine_consistency_run.py` | the SDK-compiled F1 fixture runs offline; a failed sample |
| Schema freeze | `ET/test_wire_schema_freeze.py` (unchanged) + two pinned snapshots | spec v1, evidence v1 |
| SDK unit | `ST/test_consistency_words.py`, `ST/test_consistency_api.py`, `ST/test_consistency_rebuild.py`, `ST/test_consistency_display.py`, `ST/test_consistency_docs.py` | words, API, compile, rebuild, display, docs |
| SDK fixture drift guard | `ST/test_consistency_contract_fixtures.py` | two new url4 fixtures |
| SDK contract twin | `ST/test_consistency_evidence_contract.py` | decodes the Engine cases |
| Public surface | `ST/test_public_surface.py` (existing) + pinned snapshot | `sf.Consistency`, `CombineSampleCount`, `CombineEvidence.consistency` |

## 4. Aggregate

| PRD | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|
| [consistency-record](prd/consistency-record.md) | 5 / 4 / 4 | 15 |
| [consistency-value](prd/consistency-value.md) | 5 / 2 / 8 | 14 |
| [consistency-api](prd/consistency-api.md) | 7 / 4 / 8 | 14 |
| [consistency-rebuild](prd/consistency-rebuild.md) | 3 / 6 / 5 | 9 |
| [consistency-display](prd/consistency-display.md) | 4 / 1 / 5 | 7 |
| [docs](prd/docs.md) | 2 / 0 / 2 | 5 |
| **Total** | **26 / 17 / 32** | **64** |

## 5. Not tested

| Item | Why | Revisit when |
|---|---|---|
| A live consistency run against a provider | no live calls in this build; a paid smoke may be WRITTEN later under `ST/paid/`, never run in the build | the owner asks for a paid check (D6) |
| Whether a provider honors `seed` (two calls with one seed give one answer) | a provider property, not SDK or Engine logic; the gateway cache makes a replay exact either way | D6 |
| Calibration (does a high consistency mean a correct answer) | a research question | a calibration report is planned |
| The budget stage of a sample call | the budget ledger is not wired yet (E4c) | E4c |

## 6. Fixed lists (taken on base `633fec3a1`)

A CHAR row uses these lists as they are written here. It never reads a glob or the whole file.

**L37: the 37 evidence case names** of `ET/data/combine_contract/evidence_cases.json`. The test
writes the names as a literal tuple.

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
`recipe_s10.url4`, `recipe_s11_max.url4`, `recipe_s12.url4`, `recipe_s13.url4`,
`recipe_s14.url4`, `recipe_s15.url4`, `recipe_s16.url4`, `recipe_s2.url4`, `recipe_s3.url4`,
`recipe_s4.url4`, `recipe_s4_median.url4`, `recipe_s5.url4`, `recipe_s5_pick_output.url4`,
`recipe_s7.url4`, `recipe_s8.url4`, `recipe_s8_pick_output.url4`, `recipe_s9.url4`,
`samples_vote_candidate.url4`, `signal_vote_candidate.url4`, `two_reducers_candidate.url4`,
`verbalized_vote_candidate.url4`, `vote_candidate.url4`,
`weighted_median_confidence_candidate.url4`.

**L5: the five url4 fixtures of the compile and rebuild CHAR rows** (CA#1, CB#1), a subset of L47:
`vote_candidate.url4`, `quorum_vote_candidate.url4`, `logprob_pick_mean_candidate.url4`,
`gate_judge_vote_candidate.url4`, `samples_vote_candidate.url4`. CA#1 compares each with its SDK
builder; the builders are in `ST/test_vote_median_contract_fixtures.py`,
`ST/test_quorum_url4_contract_fixtures.py`, `ST/test_logprob_entropy_url4_fixtures.py`,
`ST/test_gate_contract_fixtures.py` and `ST/test_engine_url4_contract_fixtures.py` (the RED run
finds the builder of each name; CA#1 imports, never edits, those modules). CB#1 rebuilds each with
`to_python`, runs it, and compiles it again.
