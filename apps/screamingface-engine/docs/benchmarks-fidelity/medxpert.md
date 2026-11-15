---
benchmark: medxpert
origin: screamingface
verdict: not-comparable
verdict_reason: "The turn-2 commit prompt is not the harness's conversation. The harness sends [system 'You are a helpful medical assistant.', user CoT prompt, assistant reasoning, user trigger]. Ours sends [system = the SDK's generic answer prompt, one user message holding a JSON object {question, reasoning: the candidate-invocation envelope JSON, trigger}]. The bytes differ on 2450/2450 Cases, and the deviation is undeclared: the row's Named Deviation says a solo model gets 'the official protocol exactly'. The answer reader also splits on the first trigger only, where the harness keeps just the text between the first and second trigger, which changes marks on 2 of 21 answer sheets (score-changing, unbounded). The harness's sampling (temperature 0, seed 0, max_tokens 2048/8192) is not sent either. No paid run could bring the bounds under tolerance."
audited: 2026-11-09
audited_at: 48fe0ec5b
fingerprint:
  benchmark: 1e5a3b8a461a52f7
  harness_url: https://github.com/TsinghuaC3I/MedXpertQA/tree/5f1db162d0d2b03d62da2d4fe086076a36105e18/eval
references:
  paper: https://arxiv.org/abs/2501.18362v3
  original_harness: https://github.com/TsinghuaC3I/MedXpertQA/tree/5f1db162d0d2b03d62da2d4fe086076a36105e18/eval
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "not written yet: no test sends the official rows through the harness's answer_cleansing/set_correctness; this audit's answer sheets did it in a scratch folder"
---

# MedXpertQA (Text) — Fidelity Record

## Verdict

**`not-comparable`.** Our headline would sit beside the paper's MedXpertQA Text "Avg" column, for example GPT-4o 30.37 and DeepSeek-R1 37.76 ([Zuo et al., 2025, v3, Tables 3-4](https://arxiv.org/abs/2501.18362v3)). Those numbers came from the harness [`TsinghuaC3I/MedXpertQA@5f1db162`](https://github.com/TsinghuaC3I/MedXpertQA/tree/5f1db162d0d2b03d62da2d4fe086076a36105e18/eval) running zero-shot CoT in two turns.

Four dimensions match the harness:

- **dataset:** all 2450 rows equal in order, question, options and label.
- **turn-1 prompt bytes:** equal on 2450/2450.
- **metric:** the exact letter match.
- **roll-up:** plain accuracy over every Case, equal to four decimals on 6 fixed vectors.

**The exam the Candidate sits is still not the harness's.** In turn 2 the harness continues the conversation: the model's own reasoning comes back as an assistant message, and the bare trigger follows as the last user message. Ours sends one user message holding a JSON object. That object carries the question (non-ASCII written as `\u` escapes on 1262 Cases), the reasoning wrapped in our candidate-invocation envelope JSON, and the trigger. The system message is the SDK's generic answer prompt, not the harness's "You are a helpful medical assistant." This is undeclared. The row's own Named Deviation says a solo model gets "the official protocol exactly" (`definition.py:12-15`).

Two smaller findings:

- **Answer reader.** Ours splits the reply on the first trigger only (`maxsplit=1`). The harness keeps only the text between the first and second trigger (or between the first and second " answer is "). On 2 of 21 answer sheets the two readers give different marks.
- **Sampling.** The harness sends `temperature=0`, `seed=0` and `max_tokens` 2048 (8192 for reasoning models). The Engine sends none of these: the request body carries only `model` and `messages`.

`bounds vs original harness = D1 2450/2450 (1.0000) + D2 unbounded + D3 unknown → > COMPARABLE_TOLERANCE (0.005) → not-comparable`. D4 is declared and applies to Fusion Candidates only. It does not enter a solo model's bound.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Ours:** Hub `TsinghuaC3I/MedXpertQA`, config `Text`, split `test`, revision `7e7c465a68eb2b866926bfa59c8c9d17a8daba65` (`apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/revision_inputs.py:15-21`). Case id = 1-based position (`prepare.py:74`), question verbatim (`prepare.py:87`).<br>**Theirs:** `fork:eval/data/medxpertqa/input/medxpertqa_text_input.jsonl`, index = position + 1 (`fork:eval/main.py:304`).<br>**Compared row by row (Checks 4):** `hub rows 2450 harness rows 2450`, `ids equal as sets True order equal True`, `only hub [] only harness []`, `question differs 0`, `option count differs 0`, `option text differs 0`. Labels differ only in shape: ours is `'E'`, the harness's is `['E']`, and `label differs after harness list->[0]: 0`. Every row has 10 options A-J. `emit()` accepted all 2450 rows (Checks 5). No row is excluded on either side. |
| prompt | deviation | score-changing | 2450/2450 (D1) | **Turn 1 matches:** both sides send `Q: {question}\nA: Let's think step by step.`. Ours is `prompts.py:20`, theirs `fork:eval/config/prompt_templates.py:37`. All 2450 Cases were rendered both ways: ours through the real protocol (`MEDXPERT.build(2450)` + `link_candidate` on a recording `httpx.MockTransport` gateway); theirs through the harness's own `complete_item` with a stub agent. Result: `turn1 user text differs on 0`, sha256 of the turn-1 texts `290a8cc78bc2bd36` on both sides (Checks 6-8).<br>**System message differs on 2450:** harness `'You are a helpful medical assistant.'` (`fork:eval/config/prompt_templates.py:23`, `fork:eval/main.py:204`). Ours is the SDK's `DEFAULT_ANSWER_PROMPT` (`packages/screamingface/src/screamingface/_evaluation/policy.py:7`). Our own `ANSWER_SYSTEM` (`prompts.py:17`) is never imported.<br>**Turn 2 differs on 2450:** role layouts are harness `('system','user','assistant','user')` and ours `('system','user')`, see D1.<br>**D4 (declared):** the Fusion layout. |
| answer extraction | deviation | score-changing | unbounded (D2) | Ours: `extract_choice_letter` (`answering.py:51-60`, called at `runtime.py:132`). Theirs: `answer_cleansing` zero-shot branch (`fork:eval/utils.py:53,56,61-67,80,94`). Unwanted phrases, letter range and first-match are the same on both sides.<br>Ours: `split(trigger, 1)[1]` (`answering.py:52`) and `split(" answer is ", 1)[1]` (`:54`). Theirs: `split(answer_trigger)[1]` and `split(" answer is ")[1]`, which keep only the text between the first and second occurrence. 21 answer sheets × 2450 Cases = 51,450 marks gave `differing 4900`: sheets `S16_double_answer_is` and `S17_double_trigger` on every Case (ours 1.0, harness 0.0). The other 19 sheets were identical (Checks 9-11). |
| metric | match | — | — | Ours: `correct = answered and committed == label` (`aggregate.py:168`). An empty letter counts 0.0 and stays in the denominator (`runtime.py:148`). Theirs: `set_correctness` returns `False` on an empty prediction (`fork:eval/main.py:167`) and otherwise `label[0].lower() == prediction[0].lower()` (`fork:eval/main.py:183`). Both extractors return only upper-case A-J, so the `.lower()` cannot matter. On the 19 sheets whose extraction agrees, the marks are identical on 2450/2450 Cases each: gold, `(L)`, `L.`, `L. <text>`, `**L**`, "The answer is L.", trigger echo, wrong letter, empty, lower-case, no letter, a bare "I" pronoun (0.0947 on both, the 232 label-I Cases), "No answer provided." and others (Checks 9-11). `grading.extract_letter` is not on the scoring path: it is referenced only in a comment at `definition.py:256`. |
| roll-up | match | — | — | Ours: `score=round(sum(values) / len(cases), 4)` over every selected Case (`aggregate.py:243`, `failure_policy` `withhold` at `:270`). Theirs: the `eval.ipynb` results cell, `correct / total` per split (cell 2, `Split: text … Accuracy`). Six fixed mark vectors went through our real aggregate route (end-to-end protocol) and through the harness's `complete_item` plus the notebook cell executed verbatim. all_1 1.0 / all_0 0.0 / alternating 0.5 / every_3rd 0.3331 / first_1000 0.4082 / every_7th_or_prime_ish 0.2208 on both sides (Checks 12-13). A Case that fails to run counts 0 on both sides: our `withhold` policy, and the harness's "No answer provided." after 10 retries (`fork:eval/model/api_agent.py:105`), marked wrong (sheet S19 0.0 on both). |
| judge | not applicable | — | — | No judge. Grading is a deterministic letter match on both sides (`aggregate.py:155-182`; `fork:eval/main.py:165-189`). |
| sampling | deviation | possibly-score-changing | unknown (D3) | Theirs: `temperature=self.temperature` (CLI default 0, `fork:eval/main.py:351`; `fork:eval/scripts/run.sh:12`), `seed=0`, `logprobs=True`, `max_tokens` 2048, or 8192 for o1/o3/qwq/qvq/reasoner (`fork:eval/model/api_agent.py:20,22,84,88`). The paper says "greedy decoding … if available" (§4.1). Ours: every captured request body has the keys `{('model',): 4900}` besides `messages` (Checks 8). Sampling comes only from the researcher's own `params` (`connector.py:1495,1505`; `policy.py:18-21` "only Candidate parameters the researcher explicitly selected"). `MAX_TOKENS = 8192` and `TEMPERATURE = "0"` (`revision_inputs.py:32,34`) are defined, never imported and not hashed into `compute_revision` (`definition.py:79-109`). Attempts: 1 on both sides. Two Candidate calls per Case on both sides (`interaction="multi_turn"`, `definition.py:248`). |

## Deviations

### D1 — the commit turn is one JSON user message under a different system prompt, not the harness's conversation

- **Undeclared.** The only Named Deviation on this Benchmark (`apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/definition.py:12-18`) says: "For a solo model this reproduces the official protocol exactly." The description (`definition.py:231-234`) says the same, so neither declares this difference. `prompts.py:7` says the exchange is "Ported from the official MedXpertQA harness".
- **Where.**
  - Ours: turn 2 is `candidate_call({"question": "$item.input", "reasoning": "$reasoning", "trigger": "$item.trigger"}, …)` (`definition.py:160-161`), rendered as a url4 struct. The system message is whatever the Candidate recipe carries: for a solo `sf.Model`, the SDK's `DEFAULT_ANSWER_PROMPT` (`packages/screamingface/src/screamingface/_evaluation/policy.py:7`; compile site `packages/screamingface/src/screamingface/_evaluation/candidate.py:455-462`).
  - Theirs: `messages = [{"role": "system", "content": prompt_templates.zero_shot_system_role}]` (`fork:eval/main.py:204`). Then the CoT user turn (`fork:eval/main.py:76`), the model's reasoning appended as an assistant turn (`fork:eval/main.py:92`), and the bare trigger as a new user turn (`fork:eval/main.py:107`).
- **What differs**, captured on Case 2 (Checks 8):
  - Harness: `[["system","You are a helpful medical assistant."],["user","Q: A 55-year-old postmenopausal woman …"],["assistant","Stub reasoning. …"],["user","Therefore, among A through J, the answer is"]]`.
  - Ours: `[["system","Answer the request accurately and completely. Follow every instruction and formatting constraint in the request."],["user","{\"question\": \"A 55-year-old postmenopausal woman …\", \"reasoning\": \"{\\\"schema\\\":\\\"screamingface.candidate-invocation.v1\\\",\\\"status\\\":\\\"completed\\\",\\\"output\\\":\\\"Stub reasoning. …\\\",…}\", \"trigger\": \"Therefore, among A through J, the answer is\"}"]]`.
  - Three things follow:
    1. Our model never sees its reasoning as its own assistant turn.
    2. The reasoning arrives inside our envelope JSON, double-escaped.
    3. The question is JSON-escaped: 1262 of 2450 questions carry a non-ASCII character, and all 1262 arrive as `\uXXXX` escapes in turn 2.
  - The system message differs on both turns of every Case. The harness also has per-model branches we do not reproduce: DeepSeek-R1 gets `Put your final answer within \boxed{}.` prepended to the trigger, and QVQ gets a one-turn prompt (`fork:eval/config/prompt_templates.py:30-34`). o1/o3/deepseek-reasoner calls drop the system message (`fork:eval/model/api_agent.py:62`).
- **Severity / bound.** `score-changing`, `2450/2450`: the bytes differ on every Case (`turn1 system differs on 2450`, `turn2 messages differ on 2450`). How many marks actually move needs a model run.
- **Evidence.** Checks 6-8.

### D2 — the answer reader keeps everything after the first trigger; the harness keeps only the text up to the second

- **Undeclared.** `answering.py:19` says "Ported verbatim from the official `answer_cleansing()`", and `answering.py:39` says "Port of the official `answer_cleansing()` zero-shot branch".
- **Where.** Ours: `text.split(trigger, 1)[1]` (`apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/answering.py:52`) and `text.split(" answer is ", 1)[1]` (`answering.py:54`). Theirs: `prediction.split(answer_trigger)[1]` (`fork:eval/utils.py:53`) and `prediction.split(" answer is ")[1]` (`fork:eval/utils.py:56`).
- **What differs.** When the commit reply contains the trigger, or " answer is ", twice, the harness reads only the text between the first and second occurrence; ours reads everything after the first. The marks differ when no in-range letter sits between the first two occurrences:
  - "The answer is clear: the answer is L." → harness `[]` (wrong), ours `L`.
  - Two trigger echoes followed by `L.` → harness wrong, ours `L`.
- **Severity / bound.** `score-changing`, `unbounded`: the answer sheets show 2450/2450 Cases can flip. How many real commit replies take this shape is not enumerable without replies. A free recount over any recorded run's commit outputs would count them.
- **Evidence.** Checks 9-11: `S16_double_answer_is (2450, …, 1.0, 0.0)`, `S17_double_trigger (2450, …, 1.0, 0.0)`, `marks 51450 differing 4900`.

### D3 — the harness's fixed sampling is not sent

- **Undeclared.** `revision_inputs.py:28-34` gives the reasons for `MAX_TOKENS = 8192` and `TEMPERATURE = "0"` ("The official protocol is deterministic sampling"). Nothing imports either constant (`grep -rn "MAX_TOKENS\|TEMPERATURE"` finds only their definitions and `__all__`). Neither is hashed into the revision, although `revision_inputs.py:3` says "every value here participates in the benchmark's revision hash".
- **Where.** Ours: the Engine sends `{"model", "messages", **sampling}`, where `sampling` holds only the researcher's own params (`apps/screamingface-engine/src/screamingface_engine/world/connector.py:1495,1503-1505`). Theirs: `temperature=self.temperature` (default 0), `max_tokens=self.max_tokens`, `seed=0` (`fork:eval/model/api_agent.py:84,88`). `max_tokens` is 2048, or 8192 for reasoning models (`fork:eval/model/api_agent.py:20,22`).
- **What differs.** Temperature 0, seed 0 and the 2048/8192 token cap are absent from every request we send (`our request body keys besides messages {('model',): 4900}`). The provider's defaults apply unless the researcher sets them.
- **Severity / bound.** `possibly-score-changing`, `unknown`: the effect of sampling on marks needs a paid run.

### D4 — for a Fusion the two-turn exchange wraps the whole ensemble (declared)

- **Declared.** The `NAMED DEVIATION` in the module docstring (`apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/definition.py:12-18`) and the public description (`definition.py:231-234`).
- **What differs.** A Fusion Candidate gets the reasoning prompt and the commit as two invocations of the whole recipe. A per-member implementation would run both turns inside each member. The harness has no Fusion, and the paper reports solo models only.
- **Severity / bound.** `score-changing` for Fusion Candidates, with no published reference to bound against. Bound `0` for solo models, the only kind the paper reports. It does not enter the verdict arithmetic.

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` showed only the calling session's untracked sweep ledger (`?? docs/work/2026-11-09-fidelity-sweep.md`) before and after, as expected. Every file lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-medxpert-vQB2`, deleted at the end. This report was written outside the repo.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty (`grep exit=1`). The clone, the harness venv, the Hub load and every harness script ran under that prefix with `python -I`. Our side ran with `uv run --isolated --extra inspect` from the Engine root. Its only "gateway" was an in-process `httpx.MockTransport`. No model, gateway or provider was called.
- [x] **Harness over paper.** The paper says answer cleansing follows Kojima et al. The harness's own `answer_cleansing` (two-occurrence split) is the reference. See Upstream notes.
- [x] **Declared is not a finding.** D4 is declared (Named Deviation + description) and listed. D1-D3 are undeclared findings. The Named Deviation claims the solo protocol is exact, so it does not cover D1.
- [x] **Every cell has evidence.** Each `match` names its command and output lines.
- [x] **Every `file:line` is copied from command output.** Ours: `grep -n` over `answering.py`, `prompts.py`, `revision_inputs.py`, `definition.py`, `runtime.py`, `aggregate.py`, `prepare.py`, `connector.py`, `policy.py`, and `sed -n 455,462p candidate.py`. Theirs: `grep -n` over `fork:eval/config/prompt_templates.py`, `fork:eval/main.py`, `fork:eval/model/api_agent.py`, `fork:eval/utils.py`, `fork:eval/scripts/run.sh`. Unprefixed file names in the tables are under `apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/`, except `connector.py` (`…/screamingface_engine/world/`) and `policy.py`/`candidate.py` (`packages/screamingface/src/screamingface/_evaluation/`).
- [x] **A verdict never claims more than its evidence.** None of `prompt`, `answer extraction`, `metric` or `roll-up` is `unchecked`. D3 is open, but D1 (2450/2450) already decides the verdict, and no paid run can lower it.
- No `ours` override was set.

1. `git status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md` only. `git rev-parse --short HEAD` → `48fe0ec5b`.
2. Our side: `uv run --isolated --extra inspect python -c "…medxpert.definition…"` printed:
   - `FINGERPRINT 1e5a3b8a461a52f7`, `REVISION 1e5a3b8a461a52f7`
   - `harness_url https://github.com/TsinghuaC3I/MedXpertQA/tree/5f1db162…/eval`
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='multi_turn', difficulty='hard', attempts=1)`, `case_count 2450`, `origin screamingface`
   - `inspect-evals 0.20.0`, `inspect-ai 0.3.263`

   `grep -n '"medxpert"' tests/unit/inspect/test_benchmark_fingerprints.py` → `150: "medxpert": "1e5a3b8a461a52f7"`.
3. `env -i … git clone https://github.com/TsinghuaC3I/MedXpertQA harness && git checkout 5f1db162d0d2b03d62da2d4fe086076a36105e18` → `5f1db162… Mon Sep 7 21:57:38 2026 +0800 Merge pull request #15`. `env -i … uv venv --python 3.12` + `uv pip install -r eval/requirements.txt datasets==3.6.0` → `install ok`, `nltk 3.9.1 openai 1.65.1 datasets 3.6.0`.
4. `env -i … HF_HUB_DISABLE_XET=1 venv/bin/python -I scripts/dump_hub.py` → `splits/rows 2450 columns ['id', 'question', 'options', 'label', 'medical_task', 'body_system', 'question_type']`. `scripts/cmp_dataset.py hub_rows.json fork:eval/data/medxpertqa/input/medxpertqa_text_input.jsonl` → the dataset row's lines, `option counts Counter({10: 2450})`, labels E 263 / G 263 / J 257 / B 246 / D 244 / F 243 / A 241 / C 239 / I 232 / H 222.
5. `uv run --isolated --extra inspect pytest tests/unit/test_medxpert_answering.py tests/unit/test_medxpert_protocol_turns.py tests/unit/test_medxpert_aggregate.py tests/unit/test_medxpert_prepare.py -q -p no:cacheprovider` → `44 passed in 0.74s`.
6. Our render: `uv run --isolated --extra inspect python scripts/render_ours.py hub_rows.json … n2450 "Stub reasoning. The findings favour option (C)." "C"`. The script runs `prepare.emit` on the Hub rows and builds the world with `build_aigateway_world` + `install_candidate_invocation` + `BenchmarkRegistry((MEDXPERT,))`. The Candidate is `RelExpr(path=/model, context="$input", intent=Text(DEFAULT_ANSWER_PROMPT))`, the SDK's solo-model compile. Linked with `link_candidate(…, MEDXPERT.build(2450))` under `request_scope(RequestScope(origin="run"))`, the scope `tests/conftest.py:59` binds. Output: `requests 4900 score 0.0976` (239 label-C Cases / 2450).
7. Harness render: `env -i … venv/bin/python -I scripts/render_harness.py fork:eval …text_input.jsonl … "Stub reasoning. …" "C"` ran `main.complete_item(method=zero_shot, prompting_type=cot, dataset=medxpertqa)` with a stub agent recording `messages` at each `get_response`. Output: `cases 2450 calls 4900 accuracy 0.0976`.
8. `scripts/cmp_prompts.py` printed:
   - `ours turn1 2450 turn2 2450`; `turn1 user text differs on 0 []`
   - `turn1 system differs on 2450 harness 'You are a helpful medical assistant.' ours 'Answer the request accurately and completely. …'`
   - `turn2 messages differ on 2450`
   - `role layouts (harness t1, ours t1, harness t2, ours t2): {(('system','user'), ('system','user'), ('system','user','assistant','user'), ('system','user')): 2450}`
   - `sha256 turn1 user texts ours 290a8cc78bc2bd36 harness 290a8cc78bc2bd36`
   - the Case 2 turn-2 dump quoted in D1
   - `ours turn2 user keys ['question', 'reasoning', 'trigger'] … reasoning field starts '{"schema":"screamingface.candidate-invocation.v1",…'`
   - `Cases with non-ASCII question 1262 whose turn-2 JSON carries \u escapes 1262`
   - `our request body keys besides messages {('model',): 4900}`
9. Answer sheets. `scripts/sheets.py` holds 21 templates per Case, filled from L = gold, W = next letter, C = gold option text:
   - the gold in the formats the extractor handles (`L`, `(L)`, `L.`, `L. C`, `**L**`, "The answer is L.", the trigger echoed then `L.`, "A through J, the answer is L", "The answer is (L) C")
   - wrong `W`, empty, `L, not W.`, "I think the answer is L.", lower-case `l`, "no determination was possible"
   - "I could not determine the answer." (the `answering.py` test fixtures), "No answer provided." (the harness's API-failure text)
   - `W is tempting, but the answer is L`, `W. On reflection L.`
   - the two double-occurrence replies (S16, S17)

   Harness side, `env -i … python -I scripts/sheets_harness.py` (real `complete_item`, stub agent) → S01-S07, S10, S11, S15, S18, S20 `1.0`; S08, S09, S12, S13, S16, S17, S19, S21 `0.0`; S14 `0.0947`.
10. Our side, `uv run --isolated --extra inspect python scripts/sheets_ours.py`: the real protocol, check route, case-evaluation route and aggregate, one fake-gateway world per sheet, all 2450 Cases, statuses `['scored']` on every sheet. Same scores, except S16 `1.0` and S17 `1.0`.
11. Compare → 19 sheets `(0, [])`; `S16_double_answer_is (2450, [1, 2, 3, 4, 5], 1.0, 0.0)`; `S17_double_trigger (2450, [1, 2, 3, 4, 5], 1.0, 0.0)`; `marks 51450 differing 4900`.
12. Roll-up, harness: `env -i … python -I scripts/rollup_harness.py`. Each vector's replies go through `complete_item`, then `eval.ipynb` cell 2 is `exec`'d verbatim with `split_list=["text"]`. Results: `all_1 … Correct: 2450, Total: 2450, Accuracy: 100.00% -> 4dp 1.0`; `all_0 … 0.0`; `alternating … 1225 … 0.5`; `every_3rd … 816 … 0.3331`; `first_1000 … 1000 … 0.4082`; `every_7th_or_prime_ish … 541 … 0.2208`.
13. Roll-up, ours: `uv run --isolated --extra inspect python scripts/rollup_ours.py` (the same vectors through our real protocol and aggregate) → `all_1 1.0`, `all_0 0.0`, `alternating 0.5`, `every_3rd 0.3331`, `first_1000 0.4082`, `every_7th_or_prime_ish 0.2208`, all `['scored']`.
14. Paper: `curl -sL https://arxiv.org/abs/2501.18362` → v1 30 Jan 2025, v2 20 Feb 2025, v3 6 Jun 2025. `pdftotext -layout v3.pdf` read §4.1 ("zero-shot CoT prompting … For answer cleansing, we follow the script provided by Kojima et al. … greedy decoding … if available"), Appendix C.2 (o1/R1 drop the system prompt; R1's `\boxed{}` line; QVQ one-turn), and Tables 3-4 (Text Avg: Expert 42.60, o1‡ 44.67, GPT-4o 30.37, DeepSeek-R1 37.76; ‡ = sampled subset).
15. `grep -n` citation sweeps (listed above). `wc -l fork:eval/data/medxpertqa_sampled/input/medxpertqa_sampled_text_input.jsonl` → `244`. Scratch deleted with `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"`. `git status --porcelain` afterwards → the calling session's ledger only.

## Recommended paid runs

- **Size D1 + D3 (informational; the verdict stays `not-comparable` by rule).** Take one solo model the paper reports, GPT-4o (`gpt-4o-2024-11-20`, Text Avg 30.37). Run it on a fixed 245-Case sample (every 10th Case) twice:
  1. our protocol as served;
  2. the harness's `main.py --model gpt-4o-2024-11-20 --dataset medxpertqa --task text` through our gateway, at temperature 0 and seed 0.

  The accuracy gap measures D1 + D3 together. Rerunning (1) at `temperature=0, max_tokens=2048` splits the two. That is 2 × 245 × 2 Candidate calls, no judge.
- **D2 needs no new paid run.** Count the commit outputs of any recorded MedXpert run that contain the trigger, or " answer is ", twice with no in-range letter between the first two occurrences. Over a full run, that count / 2450 is D2's bound.

## Upstream notes

- **Paper vs harness, answer cleansing.** The paper says it follows Kojima et al.'s script (§4.1). In Kojima's zero-shot CoT, the trigger is part of the prompt and the reply is not split on it. The harness instead splits the reply on the trigger and keeps the second piece (`fork:eval/utils.py:53`). The harness produced the published numbers, so it is the reference. Bound 0 on ours.
- **Paper vs harness, decoding.** The paper's "greedy decoding … if available" is the harness's `temperature=0` + `seed=0` (`fork:eval/model/api_agent.py:84,88`). The two agree. For o1/o3/deepseek-reasoner the harness sends no temperature and drops the system message (`fork:eval/model/api_agent.py:61-69`), matching Appendix C.2.
- **Some published rows are not the 2450-question exam.** o1‡ and o3-mini‡ in Tables 3-4 are "evaluated on a sampled subset". The harness switches those models to `medxpertqa_sampled` (`eval.ipynb` cell 0), whose Text file has 244 rows. A full 2450-Case run of ours sits beside the unmarked rows only.
- **Per-model re-parsing in the harness's roll-up.** `eval.ipynb` cell 1 re-reads QVQ replies by "final answer"/last-letter and DeepSeek-R1 replies by `\boxed{}` before the accuracy cell. Those rows use a different reader from the `answer_cleansing` path compared here.
- **The row's Frontier Score is not the paper's.** `FrontierScore(score=0.715, model="Gemini 3.1 Pro", source_url="https://benchlm.ai/benchmarks/medxpertqatext")` (`definition.py:283-288`) comes from a third-party leaderboard whose protocol this audit did not check. The Human Baseline 0.426 equals the paper's Expert (Pre-Licensed) Text Avg 42.60.
- **[inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0) is not in the chain.** This Benchmark is Engine-owned (`origin="screamingface"`), and no inspect_evals task is used.
