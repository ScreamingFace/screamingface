# Evaluations before and after the spec-faithful benchmark expression

Branch `url4-benchmark-expression` · 2026-10-20 · spec
`docs/spec/2026-10-20-url4-benchmark-expression-spec.md`

## 1. Method

- **Where:** the local kind cluster (`~/sf-kind`), seeded with the prod aigateway request cache
  of 2026-10-19 (622,779 rows).
- **Before:** `origin/main` 06fcb0889 — Engine image `local-06fcb08895a5` and its Client.
- **After:** this branch — Engine image `local-50a5f3bf66a0` / `local-ef2701fa6546` and its
  Client.
- **What "1:1" means:** both sides run the same Candidate on the same Cases at the same cache
  state. The aigateway cache key is the exact full model request (provider, model, every
  message, keyed parameters, prepared request, revisions, Attempt). A cache HIT on a call the
  other side made proves the two requests are byte-identical. "0 new rows" means no request
  went to a provider.
- **Report diff:** every report field is compared, except run ids, timestamps, the linked
  `url4` text and cache accounting (hit vs miss, latency, usage).

## 2. Three-case runs (Candidate `openrouter/google/gemini-3.8-flash`)

| Benchmark | Before (`origin/main`) | After (branch) | Model calls (after) | Report diff |
|---|---|---|---|---|
| ContractEval | F1 0.8 · accuracy 0.6667 · 3/3 scored | F1 0.8 · accuracy 0.6667 · 3/3 scored | 3/3 cache hits · 0 new | 0 fields |
| MedXpertQA | 0.6667 · 3/3 scored | 0.6667 · 3/3 scored | 6/6 cache hits · 0 new | 0 fields |
| FrontierScience (judged) | 0.5833 · 3/3 scored | 0.5833 · 3/3 scored | 6/6 cache hits (3 Candidate + 3 `gpt-5.4` judge) · 0 new | judge explanation text, cases 1 and 3 (note a) |
| IFEval | 1.0 · all strict/loose metrics 1.0 | 1.0 · all strict/loose metrics 1.0 | 3/3 cache hits · 0 new | 0 fields |

Notes:

- **(a)** Two `origin/main` runs of FrontierScience ran at the same time and both missed the
  same 2 judge keys; one reply filled each key. The "before" report shows its own reply; the
  branch hit the stored reply, which `origin/main` also made. Scores, answers and grades are
  equal.
- **MedXpertQA turn 2.** The first branch run missed 3 turn-2 calls. The cause predates this
  branch: turn 2 embeds the whole turn-1 record, including its cache accounting, so a turn-1
  hit or miss changes the turn-2 bytes. At the same cache state, `origin/main` hit all 6 calls
  the branch had filled (table above). In-process, both checkouts send byte-identical bodies.
  Follow-up: embed only the turn-1 output (a prompt-byte change, so it needs a revision
  decision).

## 3. Full runs of published leaderboard recipes (prod board of 2026-10-19)

The Candidate is the `url4_expression` each leaderboard entry published, linked to the current
benchmark revision (`inspect-frontierscience` 826050de44778515, `gdpval-text`
f6ea752427e71362). "Expected" is the all-case mean from the OME-1642 audit (a Case without a
grade counts 0). "Case diffs" compares every Case's status and score with the prod export.

| Benchmark / Candidate | Scored / total | Expected | After (branch) | Case diffs vs prod | Model calls |
|---|---|---|---|---|---|
| FrontierScience / claude-opus-5.5 | 136 / 160 | 0.6287 | **0.6287** | 0 | 300 hits · 0 new · $0 |
| FrontierScience / claude-fable-5.1 | 129 / 160 | 0.5958 | **0.5958** | 0 | 294 hits · 0 new · $0 |
| FrontierScience / member_synth_trio | 160 / 160 | 0.6969 | **0.6969** | 0 | 800 hits · 0 new · $0 |
| GDPval / member_synth_trio | 101 / 102 | 0.8205 | **0.8205** | 0 | 4,823 hits · 0 new · $0 |
| GDPval / sota_cheap_synth | 101 / 102 | 0.8064 | **0.8064** | 0 | 4,823 hits · 0 new · $0 |
| GDPval / external_synth_trio | 98 / 102 | 0.7935 | not validated | — | (note b) |

- **(b)** Unpublished on GDPval. The recipe published on FrontierScience misses every call on
  GDPval, so prod's GDPval run used other recipe bytes. A $0 check needs that run's report.
- The failed Cases match prod exactly: `provider_refusal` (opus 24, fable 31) and
  `model_token_cap` (GDPval case 53). Both are completed provider replies, served from the cache.

## 4. Expressions

Before (ContractEval, 3 Cases):

```
(case_evaluations:0.0:(selected_case_evaluations:0.0:/benchmarks/contracteval/890889e5b2863be4/cases()!'3'*(evaluated:0.0:(preserved_case:0.0:(candidate_invocation:0.0:(candidate_invocation:0.0:/benchmarks/candidate?web_search=false&context_format=case-v1&q=({input: '$item.input', case_id: '$item.id', case_index: '$index', case_count: '3'})!'$candidate')!'$candidate_invocation', protected_grading:0.0:({candidate_invocation: '$candidate_invocation', case_id: '$item.id'})*(grading:0.0:(record:0.0:/benchmarks/contracteval/890889e5b2863be4/check($candidate_invocation)!'$item.case_id', case_evaluation:0.0:/benchmarks/contracteval/890889e5b2863be4/case-evaluation({attempt_1: '$record'})!'$item.case_id')!'$case_evaluation')!'$grading', case_execution:0.0:/benchmarks/case-execution({case_id: '$item.id', candidate_invocation: '$candidate_invocation', grading: '$protected_grading'})!'')!'$case_execution')!'$preserved_case')!'$evaluated';iteration.concurrency=1;iteration.slice=0:3)!'$selected_case_evaluations', result:0.0:/benchmarks/contracteval/890889e5b2863be4/aggregate($case_evaluations)!'aggregate:3')!'$result'
```

After:

```
(evaluations:0.0:/benchmarks/contracteval/890889e5b2863be4/cases*(case:0.0:$item, attempt_1:0.0:/benchmarks/candidate?web_search=false&q=(case_id=$item.id, case_index=$index, case_count='3', recipe=$candidate)!'$item.input')!/benchmarks/contracteval/890889e5b2863be4/case-evaluation;iteration.concurrency=1;iteration.slice=0:3, selected:0.0:'3')!/benchmarks/contracteval/890889e5b2863be4/aggregate
```

After (MedXpertQA, 3 Cases):

```
(evaluations:0.0:/benchmarks/medxpert/1e5a3b8a461a52f7/cases*(case:0.0:$item, reasoning:0.0:/benchmarks/candidate?web_search=false&q=(case_id=$item.id, case_index=$index, case_count='3', recipe=$candidate)!'$item.cot_prompt', commit_prompt:0.0:(question=$item.input, reasoning=$reasoning, trigger=$item.trigger)!/benchmarks/medxpert/1e5a3b8a461a52f7/commit-prompt, attempt_1:0.0:/benchmarks/candidate?web_search=false&q=(case_id=$item.id, case_index=$index, case_count='3', recipe=$candidate)!'$commit_prompt', execution:0.0:(case:0.0:$item, reasoning=$reasoning, attempt_1=$attempt_1)!/benchmarks/medxpert/1e5a3b8a461a52f7/case-evaluation, case_index:0.0:$index, case_count:0.0:'3')!/benchmarks/medxpert/1e5a3b8a461a52f7/aggregate/case-result;iteration.concurrency=1;iteration.slice=0:3, selected:0.0:'3')!/benchmarks/medxpert/1e5a3b8a461a52f7/aggregate/graded
```

All 84 boards changed shape; their revision ids did not change: `air_bench`, `arc_agi_2`, `contracteval`, `draco`, `draco-3pass`, `frames_oracle`, `gdpval-text`, `healthbench-professional`, `healthbench-worst30`, `ifeval`, `infinite_bench_math_find`, `inspect-agieval_aqua_rat`, `inspect-agieval_logiqa_en`, `inspect-agieval_lsat_ar`, `inspect-agieval_lsat_lr`, `inspect-agieval_lsat_rc`, `inspect-agieval_sat_en`, `inspect-agieval_sat_en_without_passage`, `inspect-agieval_sat_math`, `inspect-aime24`, `inspect-aime25`, `inspect-aime26`, `inspect-arc_challenge`, `inspect-arc_easy`, `inspect-bbeh`, `inspect-bbq`, `inspect-boolq`, `inspect-chembench`, `inspect-coconot_contrast`, `inspect-coconot_original`, `inspect-commonsense_qa`, `inspect-cybermetric_10000`, `inspect-cybermetric_2000`, `inspect-cybermetric_500`, `inspect-cybermetric_80`, `inspect-cyse4_malware_analysis`, `inspect-cyse4_mitre_frr`, `inspect-cyse4_threat_intelligence`, `inspect-drop`, `inspect-fortress_benign`, `inspect-frontierscience`, `inspect-gsm8k`, `inspect-hellaswag`, `inspect-lab_bench_cloning_scenarios`, `inspect-lab_bench_dbqa`, `inspect-lab_bench_litqa`, `inspect-lab_bench_protocolqa`, `inspect-lab_bench_seqqa`, `inspect-lab_bench_suppqa`, `inspect-math`, `inspect-medqa`, `inspect-mgsm_en`, `inspect-mmlu`, `inspect-mmlu_pro`, `inspect-musr`, `inspect-onet_m6`, `inspect-paws`, `inspect-piqa`, `inspect-pre_flight`, `inspect-pubmedqa`, `inspect-race_h`, `inspect-sad_facts_human_defaults`, `inspect-sad_facts_llms`, `inspect-sad_influence`, `inspect-sad_stages_full`, `inspect-sad_stages_oversight`, `inspect-sevenllm_mcq_en`, `inspect-sevenllm_mcq_zh`, `inspect-simpleqa`, `inspect-simpleqa_verified`, `inspect-squad`, `inspect-stereoset`, `inspect-strong_reject`, `inspect-truthfulqa_mc1`, `inspect-uccb`, `inspect-winogrande`, `inspect-wmdp_bio`, `inspect-wmdp_chem`, `inspect-wmdp_cyber`, `inspect-worldsense`, `inspect-xstest_safe`, `inspect-xstest_unsafe`, `medxpert`, `musique`.
