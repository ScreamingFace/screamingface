---
benchmark: ifeval
origin: screamingface
verdict: comparable-to-paper
verdict_reason: ""
audited: 2026-11-09
audited_at: 064d3964f
fingerprint:
  benchmark: ada07458a23c55ab
  harness_url: https://github.com/josejg/instruction_following_eval/tree/0c495b2f95155e8b10acb919ae283bfb4d5be6e2
references:
  paper: https://arxiv.org/abs/2311.07911v1
  original_harness: https://github.com/josejg/instruction_following_eval/tree/0c495b2f95155e8b10acb919ae283bfb4d5be6e2
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: tests/unit/inspect/test_local_task_ifeval_parity.py
parity_test_reason: ""
---

# IFEval — Fidelity Record

## Verdict

**`comparable-to-paper`.** Our headline, prompt-level strict accuracy over all 541 prompts, can sit beside the [paper's Table 3](https://arxiv.org/abs/2311.07911v1) (GPT-4 76.89 / 83.57 / 79.30 / 85.37 for the four numbers). The Candidate is sent every official prompt byte for byte, the vendored checker is the fork's code with only the two documented import rewrites, our marks equal the fork's on 539 of 541 rows across 14 pre-written replies each, and the four whole-run numbers equal the fork's aggregation on four fixed mark vectors to four decimals. One declared, score-changing deviation exists (official keys 1122 and 1129, Cases 20 and 23, graded against the literal `#`/`!` where the checker draws a random letter): `sum of bounds against the original harness = 2/541 = 0.0037 ≤ COMPARABLE_TOLERANCE (0.005)`. The fork is a repackaging of Google's original checker with identical grading logic (AST-compared, see Upstream notes), so the bound against the fork is also the bound against the code that produced the paper's number.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | Hub `google/IFEval@966cd895…` loaded at the pin: 541 rows, one split `train`, key order equal to the official file's; raw Hub vs official file (`vendor/data/input_data.jsonl`, sha256 `67ffeee0…` = the fork's file at `0c495b2f`): prompt differs on keys `[2785]` only, instruction ids/kwargs differ on `[]` (`prompt_bytes.py` output, Checks run 9). Key 2785 is patched to the official text by `verify_against_official` (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/ifeval/ifeval.py:157-163`, `KNOWN_DIVERGENT_KEYS`); pinned by `test_the_one_known_hub_divergence_is_patched_and_any_other_refused` (passed). Case ids are positions 1..541 (key 1000 → Case 1, 2785 → Case 340). |
| prompt | match | — | — | All 541 Cases rendered through `load_ifeval()` + `prepared_case(…, TASK_REPLAY_CASES["ifeval"])`: `Cases whose Candidate input bytes != official prompt: []`; sha256 of the 541 inputs `9ca48d22…` equals `_HAND_BUILT_PROMPTS_SHA256` (`apps/screamingface-engine/tests/unit/inspect/test_local_task_ifeval.py:165`). The harness has no prompt builder: it grades `example.prompt` as sent (`fork:instruction_following_eval/evaluation.py:75,102-105`; README `model.generate(example['prompt'])`). Our Task sends the prompt as one user message with no system message (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/ifeval/ifeval.py:200-209`, `solver=generate()`). |
| answer extraction | not applicable | — | — | No answer is extracted: the checker reads the whole reply (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/ifeval/grading.py:41-42` → `instruction.check_following(response)`; fork `fork:instruction_following_eval/evaluation.py:107`). `scorer_reads_answer_key=False`, `target=""`. |
| metric | deviation | score-changing | 2/541 (Cases 20, 23; official keys 1122, 1129) | Checker files byte-identical to the fork but for the banner and one relative import each (`diff -r`, Checks run 4). Parity test `test_verdict_vectors_match_the_official_fork_on_every_official_row`: passed (Checks run 6). Answer sheets, 541 rows × 14 replies = 7,574 marks, ours vs the fork installed in the scratch venv, with the checker's `random` and `langdetect` pinned identically on both sides: `identical 539 differing 2` — keys 1122 and 1129 only (Checks run 11). |
| roll-up | match | — | — | Four fixed per-instruction mark vectors (all-1, all-0, alternating, every-3rd-Case-met) through our `ifeval_accuracy` and the fork's `mean`/`instruction_mean` (`fork:instruction_following_eval/evaluation.py:52-59,129-134`): all four numbers equal to four decimals on every vector, e.g. every-3rd-case-met → prompt strict 0.7153, inst strict 0.7698 (pooled over 834 instructions), prompt loose 0.9298, inst loose 0.9544 (Checks run 12-13). Google's original aggregates the same way: `prompt_correct / prompt_total`, `instruction_correct / instruction_total` (`google-research:instruction_following_eval/evaluation_lib.py:188-211`). Our loose variant list (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/ifeval/grading.py:179-186`) equals the fork's (`fork:instruction_following_eval/evaluation.py:86-94`) and the paper's eight transformations (§2.2). |
| judge | not applicable | — | — | `imported_benchmark("ifeval").judge` is `None`; the paper grades with "a simple, interpretable, and deterministic program" (p.2), no model. |
| sampling | match | — | — | Ours: `declaration=BenchmarkDeclaration(interaction='single_shot', attempts=1)`, no `max_tokens`/`temperature` on the row (grep of the local task and the row: none). The harness fixes nothing (it reads replies from a file, `fork:instruction_following_eval/evaluation.py:150-153`); the paper states only that responses were "scrapped … through API calls" in Nov/Aug 2023 (§3), no decoding settings. A knob the paper leaves open. |

## Deviations

### D1 — non-a-z `letter_frequency` letters graded literally

- **Declared.** README `local_tasks/ifeval/README.md:55-60` ("One deliberate difference from the official checker", owner decision 2026-08-10), `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/ifeval/grading.py:10-14` module docstring, `_pinned_nonalpha_letter` (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/ifeval/grading.py:101-132`), and the parity test's carve-out (`apps/screamingface-engine/tests/unit/inspect/test_local_task_ifeval_parity.py:19-23,131`).
- **Where.** Ours: `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/ifeval/grading.py:164-171` (`_build_instruction` overwrites `instruction._letter` with the dataset's literal character). Theirs: `fork:instruction_following_eval/instructions.py:1388` at `0c495b2f` (`LetterFrequencyChecker.build_description`: a letter outside a-z is replaced by `random.choice(string.ascii_letters)`).
- **What differs.** Official keys 1122 (`letter: '#'`, "include at least 4 hashtags") and 1129 (`letter: '!'`, 6 exclamation marks) are the only two rows with such a letter. The fork grades them against a random letter the prompt never mentions (and a fresh one per instantiation); we grade against `#`/`!`.
- **Severity / bound.** `score-changing`, `2/541` — Cases 20 and 23. Enumerated by the answer sheets (`identical 539 differing 2`, Checks run 11) and by a grep of the official file (`kwargs` with a one-character non-letter `letter`: exactly these two keys).

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` empty before (Checks 1) and after (Checks 14). Every file lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-ifeval`, deleted at the end.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty (`grep exit=1`). Every fork command ran under that prefix with `python -I`. No model, gateway or provider was called.
- [x] **Harness over paper.** Paper and harness agree on everything checked (Upstream notes); nothing to override.
- [x] **Declared is not a finding.** D1 is declared on the README the row's package carries and in `grading.py`; it is counted in the bound, not a finding. No undeclared difference was found.
- [x] **Every cell has evidence.** Each `match` names its command and output lines above.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`; no `possibly-score-changing` deviation is open.
- No `ours` override was set.

1. `git status --porcelain` → empty; `git rev-parse --short HEAD` → `064d3964f`.
2. Our side: `uv run --isolated --extra inspect python -c "imported_benchmark('ifeval')"` → `fingerprint ada07458a23c55ab`, `origin screamingface`, `harness_url https://github.com/josejg/instruction_following_eval/tree/0c495b2f…`, `paper_url https://arxiv.org/abs/2311.07911`, `judge None`, `declaration=BenchmarkDeclaration(interaction='single_shot', attempts=1)`; `inspect-evals 0.20.0`, `inspect-ai 0.3.263`, ours `nltk 3.10.3`, `langdetect 1.0.9`.
3. `git clone https://github.com/josejg/instruction_following_eval harness && git checkout 0c495b2f95155e8b10acb919ae283bfb4d5be6e2` → `0c495b2f… 2025-01-16 "fix"`. `env -i … uv venv --python 3.12` + `uv pip install -e .` → `install ok`, `nltk 3.10.4`, `langdetect 1.0.9`.
4. `diff -r -x __pycache__ -x __init__.py -x LICENSE vendor/ harness/instruction_following_eval/`: `instructions.py`, `instructions_registry.py`: 3-line banner + `from . import …` vs `from instruction_following_eval import …`; `instructions_util.py`: banner only; `evaluation.py`: banner + relative import, and the typer/rich CLI, `get_examples`, `print_report`, `main`, `ensure_nltk_resource` absent (as its banner documents); `test_instruction_following`, `mean`, `instruction_mean`, `evaluate_instruction_following` lines identical. `shasum -a 256 data/input_data.jsonl` both `67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49`, 541 lines each.
5. `arxiv.org/abs/2311.07911` → "v1 … 14 Nov 2023", the only version. PDF read (pp.1-6): 541 prompts, 25 instruction types, strict = eq.1, loose = any of 8 transformations (remove `*`/`**`, first line, last line, their combinations, identity), the four metrics (§3), Table 3 numbers, no decoding settings stated.
6. `uv run --isolated --extra inspect pytest tests/unit/inspect/test_local_task_ifeval_parity.py tests/unit/inspect/test_local_task_ifeval.py::test_every_prompt_is_the_hand_built_one_with_the_official_text tests/unit/inspect/test_local_task_ifeval.py::test_the_one_known_hub_divergence_is_patched_and_any_other_refused -q -p no:cacheprovider` → `4 passed in 8.03s`.
7. Answer sheets, fork side: `env -i … venv/bin/python -I scripts/sheets.py fork input_data.jsonl` (14 replies per row: the parity test's 4 canned replies, the empty reply, a `***`-separated postscript reply, a JSON reply, "My answer is yes.", a 350-word lorem reply, one reply built to satisfy each instruction's arguments, one built to break them, the prompt echoed, quoted and upper-cased; `random.choice/randint/sample` pinned as in the parity test) → `fork rows 541 sheets/row 14 marks 7574`.
8. Answer sheets, our side: `uv run --isolated --extra inspect python scripts/sheets.py ours …` → `ours rows 541 sheets/row 14 marks 7574`. Compare → `identical 536 differing 5`: keys 1122, 1129 (expected) and 2724, 2943, 3456 (unexpected; all carry a langdetect-backed instruction: `language:response_language`, `change_case:english_lowercase`, `change_case:english_capital`; on 2724 the fork marked strict True but loose False on the same reply, impossible for a deterministic checker).
9. Prompt bytes: `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python scripts/prompt_bytes.py` → `hub splits ['train'] rows 541`; `hub key order == official key order: True`; `raw hub vs official: prompt differs on keys [2785]; ids/kwargs differ on keys []`; `loaded samples 541 ids 1 .. 541`; `Cases whose Candidate input bytes != official prompt: []` (Grading Material ids/kwargs also equal on all 541); `official key -> Case id: {1000: 1, 1122: 20, 1129: 23, 2785: 340}`; `sha256 of all inputs: 9ca48d22…` = `_HAND_BUILT_PROMPTS_SHA256`.
10. Fork against itself: a second unseeded fork run → `rows compared 541 identical 539 differing 2` (keys 2724, 3456): the fork's own marks move between runs on langdetect rows.
11. Sheets rerun with `langdetect.DetectorFactory.seed = 0` added on both sides (as the parity test does): `identical 539 differing 2` — `official key 1122 = Case 20`, `official key 1129 = Case 23`, nothing else.
12. Roll-up, fork: `env -i … python -I scripts/rollup.py fork …` → `cases 541 instructions 834`; all-1 → 1.0000 ×4; all-0 → 0.0000 ×4; alternating-per-instruction → 0.2810 / 0.5000 / 1.0000 / 1.0000; every-3rd-case-met → 0.7153 / 0.7698 / 0.9298 / 0.9544.
13. Roll-up, ours: `uv run --isolated --extra inspect python scripts/rollup.py ours …` → the same four lines, digit for digit.
14. Google's original: `git clone --depth 1 --filter=blob:none --sparse https://github.com/google-research/google-research` + `sparse-checkout set instruction_following_eval` → HEAD `0eebfd4` (2026-11-06). AST compare with docstrings stripped and `absl.logging.error`/`log.error` normalised: `instructions.py`, `instructions_util.py`, `instructions_registry.py` → `differing-after-normalising=[]` (only `from absl import logging` → stdlib `logging` and an unused `typing.List` import differ). `google-research:instruction_following_eval/evaluation_lib.py:121-130` lists the same 8 loose variants; `:188-211` pools instructions. `rm -rf "$SCRATCH"`; `git status --porcelain` → empty.

## Recommended paid runs

none

## Upstream notes

- **Paper vs harness: agree.** The paper's eight loose transformations (§2.2) are the fork's eight variants (`fork:instruction_following_eval/evaluation.py:86-94`) and Google's (`google-research:instruction_following_eval/evaluation_lib.py:121-130`); the paper's "percentage of prompts"/"percentage of instructions" (§3) is the harness's `prompt_correct/prompt_total` and pooled `instruction_correct/instruction_total`. Bound 0.
- **Fork vs Google's original: grading logic identical.** [`josejg/instruction_following_eval@0c495b2f`](https://github.com/josejg/instruction_following_eval/tree/0c495b2f95155e8b10acb919ae283bfb4d5be6e2) is a pip-installable repackaging (its README) of [`google-research/instruction_following_eval`](https://github.com/google-research/google-research/tree/master/instruction_following_eval): after formatting, docstrings and the absl→stdlib logging swap are normalised, the three checker modules have no differing node (Checks run 14), and the dataset file is byte-identical. Compared against Google's current master (`0eebfd4`, 2026-11-06), not the 2023 commit the paper's number used; the blobless sparse clone carries no history. Bound 0 on what was compared.
- **The checker is non-deterministic on langdetect-backed rows, upstream and ours alike.** `language:response_language`, `change_case:english_capital` and `change_case:english_lowercase` call `langdetect.detect`, whose RNG is unseeded; the fork disagreed with itself on 2 of 541 rows between two runs over the same 14 replies (Checks run 10), and the run-to-run flips vanished once `DetectorFactory.seed` was pinned (Checks run 11). 95 of 541 rows carry one of these three instructions. This is reproducibility noise inherent to the published checker, not a difference between examiners: our `grading.py` seeds nothing either, so a live run inherits it exactly as the paper's did. Not counted as a deviation; worth an owner call on whether to pin `langdetect.DetectorFactory.seed` at grading (a Named Deviation that would make our marks stabler than the harness's).
- **[inspect_evals' `ifeval` (v0.20.0)](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/ifeval) is not the reference and is not used** (README): it pins the same fork (`inspect_evals:ifeval/ifeval.py:42-46`) but publishes `final_acc`, a weighted average of the four numbers, as its metric (`inspect_evals:ifeval/ifeval.py:112-123`), not the paper's prompt-level strict headline.
