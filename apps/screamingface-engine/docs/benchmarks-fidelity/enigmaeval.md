---
benchmark: enigmaeval
origin: screamingface
verdict: unverified
verdict_reason: "Two declared differences are possibly-score-changing and still open, and only a paired Candidate run can size them. (1) The authors send their system prompt as a system message. We send the same bytes as the first text of the one user turn. (2) The authors fall back to the provider's reasoning text when the reply text is empty. We read the reply text only. The one measured difference, 3 of 1,161 puzzles held out over the 8 MB Case cap, is bounded at 3/1161 = 0.0026 ≤ 0.005. Every deterministic check matches the authors' harness at 6614edf. Case Digest and case-set digest both reproduce on linux/amd64. System and user text are byte-equal on 1,158/1,158 Cases. Decoded pictures are equal on 1,327/1,327. Marks agree on 18,528/18,528 answer sheets outside the declared reasoning-fallback sheet. Roll-up is equal to four decimals on 7/7 mark vectors. The paper's Table 2 (o1 7.0% normal, 0.0% hard) is on the first release, a different puzzle set with a different answer format, so it cannot sit beside ours. No v2 number by a named model was found."
audited: 2026-11-16
audited_at: 53226e08c
fingerprint:
  benchmark: 863b8c98762520a2
  harness_url: https://github.com/centerforaisafety/simple-evals/tree/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval
references:
  paper: https://arxiv.org/abs/2502.08859v2
  original_harness: https://github.com/centerforaisafety/simple-evals/tree/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: tests/unit/inspect/test_local_task_enigmaeval.py
parity_test_reason: ""
---

# EnigmaEval — Fidelity Record

## Verdict

**`unverified`.** Our headline is the mean mark over the 1,158 served Cases, with a failed Case counted 0 (`withhold`). The reference is the authors' v2 harness, [centerforaisafety/simple-evals at `6614edf`](https://github.com/centerforaisafety/simple-evals/tree/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval), whose own headline is "Overall accuracy" over all 1,161 puzzles. **On every free check, ours marks like theirs.**

- The sealed Case Digest `2534208d…` and case-set digest `58b8cd38…` reproduce from the pinned parquet in a linux/amd64 container.
- System text, user text and gold are byte-equal on 1,158/1,158 Cases. The 1,327 pictures decode to equal pixels.
- The marks are equal on 18,528/18,528 answer sheets (16 reply shapes × 1,158 Cases).
- The authors' own `main()` and our `finalize_candidate_result` give the same headline to four decimals on 7/7 mark vectors, failures included.

Three declared differences remain:

| | difference | measured bound |
|---|---|---|
| D3 | three puzzles over the 8 MB Case cap are held out | 3/1161 = 0.0026 |
| D1 | the authors' system message reaches the Candidate as the first text of the user turn | `unknown`, possibly-score-changing |
| D2 | when a reply's text is empty, we do not fall back to its reasoning text | `unknown`, possibly-score-changing |

`sum of measured bounds against the original harness = 3/1161 = 0.0026 ≤ COMPARABLE_TOLERANCE (0.005)`, with D1 and D2 open → `unverified`.

The paper's Table 2 (o1 7.0% normal, 0.0% hard) cannot sit beside our headline whatever the paired run shows:

- it is on the first release (1,184 puzzles);
- its answers were read from an `Answer:` line;
- it reports per split, averaged over 3 runs.

That is a paper-versus-harness disagreement, so it is recorded in Upstream notes. No v2 score by a named model was found, so today there is no published number to set ours beside.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | score-changing | 3/1161 (D3) | **Ours:** `cais/EnigmaEval` at `9ed38dab…`, split `test` (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/enigmaeval/enigmaeval.py:56,155`; `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:2308`), 1,161 rows (`enigmaeval.py:61`), file order, three held out (`prepare.py:202,2306`). **Theirs:** `load_dataset("cais/EnigmaEval", split="test")` with no revision, then `.shuffle(seed=42)` (`fork:enigmaeval/enigmaeval_utils.py:152-156`). Default split `all` keeps every row, Ring Toss included (`fork:enigmaeval/enigmaeval_utils.py:62`). The Hub HEAD today is `9ed38dabb105ad900ef850a937014d8653ae9f94`, our pin (Checks run 4). Parquet sha256 `00e89624…5e73392`, 345,273,199 bytes. **Ids:** 1,161 on both sides; only-authors `[]`, only-ours `[]`; gold differs on 0/1,161 (Checks run 9). Our Linux rebuild reproduces Case Digest `2534208d…` and case-set digest `58b8cd38…`, both equal to the declared values (`prepare.py:2301`; Checks run 7). Order (file vs shuffle 42) is cosmetic for a full-run mean, bound 0. |
| prompt | deviation | possibly-score-changing | `unknown` (D1) | **Text:** our Samples equal the authors' `grade_puzzles` messages on 1,161/1,161 puzzles (system, user text, pictures, gold). Our sealed Cases equal them on 1,158/1,158. In the 1,046 picture Cases, part 1 = the authors' system text and part 2 = their user text, byte for byte. In the 112 text-only Cases, the input = system + `"\n\n"` + user (Checks run 9). Ours: `enigmaeval.py:90-106,116-146,190`. Theirs: `fork:enigmaeval/enigmaeval_utils.py:252-284,321-348`, `fork:enigmaeval/enigmaeval_eval.py:179-205`. **Pictures:** both builders run on this Mac with Pillow 13.0.0, so the data URIs are byte-equal, 1,327/1,327. Our linux/amd64 sealed bytes equal the Mac bytes on 0/1,327, which is the platform difference the row declares. Decoded (format, mode, size, raw pixels) they are equal on 1,327/1,327. Order and count are equal, and `image_url` holds only `url` on both sides. Negative control: one flipped byte or one changed pixel was caught (Checks run 10). **Role:** D1. |
| answer extraction | deviation | possibly-score-changing | `unknown` (D2) | Our reader and normaliser are the authors' functions. `standardize`, `extract_answer_from_response`, `evaluate_answer`, `_pil_to_base64_png` and `get_answer_type` in `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/enigmaeval/vendor/simple_evals.py:45,57,70,83,96` equal `fork:enigmaeval/enigmaeval_eval.py:38,65,78` and `fork:enigmaeval/enigmaeval_utils.py:123,205` with trailing whitespace stripped. The tips constants equal the authors' files byte for byte (Checks run 11). Input to the reader: ours is the reply text only (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:612`, `enigmaeval.py:257`). Theirs is `response.content or response.reasoning_content or ""` (`fork:enigmaeval/enigmaeval_eval.py:123`). That is D2: on the reasoning-only sheet, marks differ on 1,158/1,158 (Checks run 12). |
| metric | match | — | — | **Answer sheets:** 17 reply shapes × 1,158 Cases = 19,686 sheets. Ours ran through the real hook, `inspect_grade_case(enigmaeval_exact_match())`, on the sealed Linux Cases. Theirs ran through `grade_puzzles → get_puzzle_prediction → extract_answer_from_response → evaluate_answer` with a stub agent. `marks differ 1158`, all on `gold_in_reasoning_only` (D2). **The other 16 shapes, 18,528 sheets, differ on 0.** Per-shape counts are equal on both sides, for example `gold_as_written 1153/1158`, `gold_commas_dropped 1089/1158`, `gold_untagged 0/1158`, `wrong_box_first 0/1158`, `gold_box_first 1158/1158` (Checks run 12). Rule: right → 1, wrong → 0 (`enigmaeval.py:259` vs `fork:enigmaeval/enigmaeval_eval.py:139-140`). |
| roll-up | match | — | — | **Ours:** `_accuracy` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1173,1288`; whole-run metric factory `None`) under `withhold`, every selected Case in the denominator (`apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py:94,106`). **Theirs:** `accuracy = total_correct / denom` with `denom = total_puzzles`, a failed call counting 0 (`fork:enigmaeval/enigmaeval_eval.py:391-392,419`). Their real `main()` and our `finalize_candidate_result` were run on the same per-Case marks. Results: `all_1 0.9957/0.9957`, `all_0 0.0000/0.0000`, `alternating 0.4974/0.4974`, `first_100_right 0.0864/0.0864`, `random_7pct 0.0820/0.0820`, `alternating_every_9th_fails 0.4421/0.4421` (129 failed calls), `all_fail_but_one_right 0.0009/0.0009`. `equal_4dp True` on 7/7 (Checks run 13). Both pool normal and hard puzzles into one headline. |
| judge | not applicable | — | — | No judge on either side: deterministic string match (`enigmaeval.py:229-267`; `fork:enigmaeval/enigmaeval_eval.py:139-140`). |
| sampling | match | — | — | Neither side fixes a Benchmark-level temperature, token cap or seed. **Ours:** `BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`, `params None` (Checks run 5), `solver=generate()` (`enigmaeval.py:279`). **Theirs:** generation settings come per model from `fork:configs/models.yaml`, for example `max_tokens: 40000` at line 10 and `reasoning_effort: high` at line 20. The README asks for "a generous max-output-token budget" (`fork:README.md:444`). One call per puzzle (`fork:enigmaeval/enigmaeval_eval.py:120`); one Attempt on both sides. The paper uses "the default model temperature" and averages 3 runs (Upstream notes). Transport retries differ: our connector retries 429/5xx, while theirs relies on the provider SDK's own behaviour. That changes only how many calls fail, and a failed call is 0 on both sides. |

## Deviations

### D1 — the authors' system prompt reaches the Candidate as the first text of the user turn

- **Declared.** README `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/enigmaeval/README.md:81-83` and the row description `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:7858-7860`. There is no `# NAMED DEVIATION` comment on the row; the declaration is the description plus the Task README.
- **Where.** Ours: the Task builds a `ChatMessageSystem` (`enigmaeval.py:190`). Case Preparation folds it into the user message: as the first text part for picture Cases (`apps/screamingface-engine/src/screamingface_engine_inspect/picture_input.py:127-129`), and joined with `"\n\n"` for text-only Cases (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:79,538`). Theirs: `{"role": "system", "content": system_prompt}` (`fork:enigmaeval/enigmaeval_eval.py:194`).
- **What differs.** The bytes do not differ (Dimensions, prompt). The role does, on all 1,158 Cases. A text-only Case is also one string rather than a one-part list.
- **Severity / bound.** `possibly-score-changing`, `unknown`. Whether a Candidate follows the tips and answer-type sentence the same way in the user turn depends on the Candidate.
- **Evidence.** Checks run 9.

### D2 — no fallback to the reasoning text when the reply text is empty

- **Declared.** README `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/enigmaeval/README.md:84-85`, row description `benchmarks.py:7860-7861`.
- **Where.** Ours: `scorer_adapter.py:612`, where no answer text becomes `""`. Then `enigmaeval.py:257` reads `state.output.completion`. Theirs: `content = response.content or response.reasoning_content or ""` (`fork:enigmaeval/enigmaeval_eval.py:123`).
- **What differs.** A reply with empty text whose reasoning holds `<answer>gold</answer>` scores 1 for them and 0 for us. On the `gold_in_reasoning_only` sheet the marks differ on 1,158/1,158 Cases. A reply with any non-empty text is read the same way on both sides.
- **Severity / bound.** `possibly-score-changing`, `unknown`. The bound equals the number of Cases where the Candidate returns no text but its reasoning carries a tagged answer, which depends on the provider and the token budget. Any real run's Report can give a free upper bound: the count of Cases with empty reply text.
- **Evidence.** Checks run 12.

### D3 — three puzzles over the 8 MB Case cap are held out

- **Declared.** `excluded_sample_ids=ENIGMAEVAL_HELD_OUT_OVER_CASE_CAP` (`prepare.py:202,2306`), README `README.md:86`, row description `benchmarks.py:7861-7862`.
- **Where.** Ours serves 1,158 Cases. Theirs runs 1,161 puzzles (`fork:README.md:450`).
- **What differs.** Three puzzles are not served:
  - `69f3aee766ce8458f2f20eb8` (Puzzle Potluck, 1 picture): 9,690,687 bytes as the authors would send it.
  - `69f3aee766ce8458f2f20eb0` (Puzzle Potluck, 1 picture): 11,996,751 bytes.
  - `69f3aee766ce8458f2f20fa8` (PuzzledPint, 7 pictures): 20,375,529 bytes.

  The largest kept puzzle is 5,921,508 bytes, and no kept puzzle is over 8,000,000 (Checks run 14).
- **Severity / bound.** `score-changing`, `3/1161 = 0.0026`. With c right on our 1,158 and k ∈ {0..3} right on the three, |c/1158 − (c+k)/1161| ≤ 3/1161.
- **Evidence.** Checks run 7, 9, 14.

## Checks run

**Rules checklist**

- [x] **Read-only on the checkout.** `git status --porcelain` was empty before the audit at `b184edee3` and empty after it at `53226e08c`. Every file lived under one `SCRATCH=$(mktemp -d …/fid-enigma.XXXX)`, removed at the end with `rm -rf "$SCRATCH"` (confirmed gone). pytest ran with `-p no:cacheprovider` and every Python command with `PYTHONDONTWRITEBYTECODE=1`.
  - Two commits landed on the PR branch during the audit: `aabcd8ee9` and `53226e08c`, at 10:26 and 10:32 ICT. `git diff --stat b184edee3 HEAD -- apps/screamingface-engine/src` is empty. They touch only the test file, the ledger, the test-change approval and the SDK notebook.
  - The fingerprint is `863b8c98762520a2` at both heads.
  - The test file was re-run at `53226e08c`.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` printed nothing (exit 1).
  - The token was used once, for the pinned download only (step 2), from our Engine env. It was never printed.
  - Every later command ran under `env -i … HF_HUB_OFFLINE=1`.
  - The linux/amd64 container got no token. Its env grep printed only `GPG_KEY=7169605F…`, the Python image's public release-signing key id.
  - No model, gateway or provider was called; the authors' model calls went to a stub.
- [x] **Harness over paper.** The paper and the dataset card disagree with the harness, so both go to Upstream notes.
- [x] **Declared is not a finding.** D1, D2 and D3 are declared (row description, Task README, `excluded_sample_ids`). No undeclared difference was found.
- [x] **Every cell has evidence.** All four free checks ran: prompt bytes, answer sheets, roll-up, and the Case Digest rebuild.
- [x] **Every `file:line` is copied from command output.** The grep commands are listed below. The calling session re-opened a sample of 28 our-side and 18 `fork:` citations with `sed -n '<n>p'` at `53226e08c` and `6614edf`, and each showed the cited line.
- [x] **Every citation names its tree.** Prefixes are defined below.
- [x] **A verdict never claims more than its evidence.** D1 and D2 are open with bound `unknown` → `unverified`.

**Trees and prefixes**

- `fork:` is [centerforaisafety/simple-evals at `6614edf59833140fb77e61758bbb2674b54a445e`](https://github.com/centerforaisafety/simple-evals/tree/6614edf59833140fb77e61758bbb2674b54a445e), the clone root. It is branch `dev` HEAD; `git log 6614edf..origin/dev -- enigmaeval` is empty, and `main` has no `enigmaeval` path.
- `card:` is the dataset card [`cais/EnigmaEval` README at `9ed38dab`](https://huggingface.co/datasets/cais/EnigmaEval/blob/9ed38dabb105ad900ef850a937014d8653ae9f94/README.md), cited as `card:README.md:<n>`.
- `cais-private:` is [justinphan3110cais/enigmaeval-eval at `2a48b200`](https://github.com/justinphan3110cais/enigmaeval-eval/tree/2a48b200a07d524c05bd81ca0ec1e471bde69c01), "EnigmaEval code for private dataset" (2025-12). It is not pinned by the row and is cited only in Upstream notes.
- `paper:` is [arXiv 2502.08859v2](https://arxiv.org/abs/2502.08859v2), cited by section and table. The arXiv API lists `2502.08859v2` (updated 2025-02-14) as the latest version.

**Gated dataset: option 2.** There was no local snapshot, so the token was used for the pinned download only, from our Engine env. Every later read used that local copy with `HF_HUB_OFFLINE=1`.

**Steps**

1. **Clone the harness.** `git clone https://github.com/centerforaisafety/simple-evals.git harness && git checkout 6614edf…` → `6614edf… Thu Jul 23 17:47:17 2026 Add EnigmaEval eval (public cais/EnigmaEval dataset)`.
2. **Download the pinned dataset** (token step), from `apps/screamingface-engine`: `uv run --isolated --extra inspect python -I -c "snapshot_download('cais/EnigmaEval', repo_type='dataset', revision='9ed38dab…', local_dir=$SCRATCH/data)"`. Result: 3 files. `shasum -a 256 data/test-00000-of-00001.parquet` → `00e896247804d22d4fe8a30783701bdf7f543bd14476eb1d69fea17795e73392`, 345,273,199 bytes.
3. **Read the authors' code and docs:**
   - `cat -n` of `enigmaeval/enigmaeval_eval.py`, `enigmaeval/enigmaeval_utils.py` and `enigmaeval/README.md`;
   - `grep -n -A25 '### EnigmaEval' README.md`;
   - `grep -n -E 'temperature|max_tokens|reasoning|effort' configs/models.yaml`;
   - `cat -n` of the dataset card.
4. **Check Hub HEAD, anonymously** (`env -i`, `HfApi(token=False).dataset_info('cais/EnigmaEval')`) → `HEAD sha 9ed38dabb105ad900ef850a937014d8653ae9f94 last_modified 2026-07-23 gated auto`.
5. **Read our declaration** (`env -i … uv run --isolated --extra inspect python decl.py`) → `fingerprint 863b8c98762520a2`, `BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`, `params None`, `spec 1158 2534208d… 58b8cd38… (3 ids) {'cais/EnigmaEval': '9ed38dab…'} True`. Re-run at `53226e08c` → `fingerprint 863b8c98762520a2`.
6. **Build our Cases on the Mac.** Our real `enigmaeval()` Task plus `captured_case_records` (`env -i … HF_HUB_OFFLINE=1 uv run --isolated --extra inspect python ours_build.py`). The only patch: `load_rows` reads the local parquet instead of the Hub, with the same features (`images: List(Image)`) and the same row-count check. Output: `samples 1161`, `prepared 1158`, `case_digest dc765b66…d2148`. This equals the Mac seal the ledger reports and discarded.
7. **Rebuild our Cases on linux/amd64.** `docker run --platform linux/amd64 ghcr.io/astral-sh/uv:python3.13-bookworm-slim`, mirroring the Engine Dockerfile builder: `uv sync --frozen --no-dev --extra inspect` on a tar copy of `packages/url4` and the Engine `pyproject.toml`, `uv.lock` and `src/` (read-only mount). Output: `x86_64`, `pillow 13.0.0 datasets 5.1.0`, then:
   - `case_digest 2534208d6af2d6c7544bff23a086dd4624080242a77606deff20f08ccc413418 declared 2534208d…`
   - `case_set_digest 58b8cd38f362d6ab7c7fd4f5f684d00aabaec10693a0be54f225afda30a66fb4 declared 58b8cd38…`
8. **Run the authors' harness.** venv: `uv venv --python 3.13` plus `uv pip install -r requirements/base.txt pillow==13.0.0`, plus `litellm`, which `base.txt` omits though `fork:shared/llm_agents.py:13` imports it. Script `authors_run.py`, under `env -i … HF_HUB_OFFLINE=1`:
   - the authors' `fetch_puzzles(Namespace(split="all", exclude_meta=False, text_only=False))`, with `datasets.load_dataset` answered from the pinned parquet. Their call was `[('cais/EnigmaEval', 'test', [])]`, 1,161 puzzles.
   - the authors' `grade_puzzles` with a stub agent. Pass 0 captured every puzzle's messages: `captured messages for 1161`.
9. **Compare prompt text** (`compare_prompts.py`):
   - `ids authors 1161 ours samples 1161 only authors [] only ours []`
   - `Sample vs authors … differing puzzles: {'system': 0, 'user': 0, 'pictures': 0, 'gold': 0, 'ntext': 0}`
   - `pictures total 1336 text-only 112`
   - `MAC sealed cases 1158 ids == authors minus held: True`, `Case 1..N follow file order minus held: True`, `mismatches {}`
   - `LINUX sealed … mismatches {}`
10. **Compare pictures, with a negative control:**
    - `MAC sealed pictures 1327 data-URI bytes equal 1327 decoded pixels equal 1327 image_url keys {('url',): 1327}`
    - `LINUX sealed pictures 1327 data-URI bytes equal 0 decoded pixels equal 1327 image_url keys {('url',): 1327}`
    - Negative control: `system mismatches after flipping one byte: ['69f3aee766ce8458f2f21068'] expected ['69f3aee766ce8458f2f21068']`; `one-pixel change detected by pixel compare: True`.
11. **Diff the vendored code** (AST extraction, trailing whitespace stripped): `standardize`, `extract_answer_from_response`, `evaluate_answer`, `_pil_to_base64_png` and `get_answer_type` all `equal … True`. `STANDARD_TIPS == standard_tips.txt bytes: True`; `MIT_TIPS == mit_tips.txt bytes: True`.
12. **Run the answer sheets** (`sheets.py`, the same bytes on both sides; ours via `ours_sheets.py` on the sealed Linux Cases). 17 shapes: gold as written, after a worked solution, lowercase, upper-case tags across lines, padded, last `|` alternative, comma set reversed, spaces removed, hyphenated, commas dropped, untagged, wrong, empty tags, empty reply, wrong box first, gold box first, gold only in reasoning text. Output: `sheets 19686 marks differ 1158 {'gold_in_reasoning_only': 1158}`. Empty reply and reasoning-only score `0.0` on ours. The 5 `gold_as_written` misses on both sides are the five `|` golds (`BEYONCE | BEYONCÉ`, `FRIDGE | REFRIGERATOR`, `HOMONYM | HOMONYMS`, `GABON | LIBREVILLE`, `MARSHALL | ROB MARSHALL`).
13. **Compare roll-ups.** `vectors.py` builds 7 vectors over the 1,158 kept ids (seed 20261116). The authors' `main()` ran with `fetch_puzzles` returning those 1,158 and `get_llm_agent_class` returning the stub, with `--model gpt-5-mini --models_config configs/models.yaml`. Their `metrics_summary` line was read back, and their per-puzzle `is_correct` and `model_response is None` were fed to our `finalize_candidate_result(…, scorer=_accuracy, failure_policy='withhold')`. Output: `ROLLUP … equal_4dp True` ×7, the values as in Dimensions.
14. **Measure sizes** (authors' messages as JSON): held out 9,690,687 / 11,996,751 / 20,375,529 bytes; `largest kept 5921508 kept over 8,000,000: 0`.
15. **Dataset facts** (pyarrow): `comma golds 69 pipe golds 5`, `blank question 0`, `MIT with prev 0`, `prev rows 67`. Comparing the card's builder with the harness: `image-sentence rule differs … 20`, `MIT Mystery Hunt rows … 68`, `union … 83`.
16. **Parity test:** `env -i … uv run --isolated --extra inspect pytest -p no:cacheprovider tests/unit/inspect/test_local_task_enigmaeval.py -q` → `37 passed, 1 warning` at `b184edee3` and again at `53226e08c`. It pins the vendored-function sha256 and the prompt hashes against the authors' builder on real and synthetic rows. The cross-harness evidence over every row is steps 6-13.
17. **The paper:** `curl` of the arXiv API and the PDF, then `pdftotext`. Read §3.1 (Evaluation Setup), Table 2, Appendix B.2 (Prompt Templates) and B.4 (Answer Extraction).
18. **inspect_evals:** `gh api repos/UKGovernmentBEIS/inspect_evals/contents/src/inspect_evals?ref=v0.20.0` → 137 entries, 0 match `enigma`. There is no inspect_evals reference.

**Recorded replies: none found.** Where I looked:

- simple-evals: the `dev` HEAD is the pin, and `git ls-tree -r origin/dev | grep -iE 'result|\.jsonl'` finds no results. `main` has no EnigmaEval.
- The CAIS Hugging Face organisation: `list_datasets/models/spaces(author='cais')` → 14 datasets, 8 models and 1 space, none holding EnigmaEval replies.
- Hugging Face search for `enigma`: only `ScaleAI/EnigmaEval` (a dataset, `data/train-00000-of-00001.parquet`) and `ScaleAI/EnigmaEval-archived` (the v1 dataset, 2025-04-10), both data only.
- GitHub: `search/code q=enigmaeval org:centerforaisafety` → 2 unrelated hits (`erqa`, `intphys2`). `gh search repos enigmaeval` → `justinphan3110cais/enigmaeval-eval`, code only, no results.
- [dashboard.safe.ai](https://dashboard.safe.ai) and [Scale's board](https://labs.scale.com/leaderboard/enigma_eval) were not fetched. They publish scores, not replies, and the row reads the dashboard as showing no EnigmaEval score on 2026-11-13.

So there is no headline comparison over recorded replies.

**Line-number commands.** Every line number in this record was taken from one of these (or from `cat -n` / `diff` hunks of the pinned files):

- `grep -n 'DATASET_REVISION: Final\|ROW_COUNT: Final\|…\|solver=generate' …/enigmaeval/enigmaeval.py`
- `grep -n '^def ' …/enigmaeval/vendor/simple_evals.py`
- `grep -n 'Named deviations\|…' …/enigmaeval/README.md`
- `grep -n 'ENIGMAEVAL_HELD_OUT_OVER_CASE_CAP: tuple\|…' prepare.py`
- `grep -n 'key="enigmaeval"\|…' benchmarks.py` and `awk 'NR>=7837 && NR<=7950 && /failure_policy=|frontier_score=|harness_url=/'`
- `grep -n '^_MESSAGE_SEPARATOR\|return _MESSAGE_SEPARATOR.join' capture.py`
- `grep -n '^_SYSTEM_SEPARATOR\|system_text…\|parts.append…' picture_input.py`
- `grep -n 'completion: str = ""…' scorer_adapter.py`
- `grep -n '^def _accuracy\|^            _accuracy$' single_shot.py`
- `grep -n '^def policy_cases\|return tuple(cases) if…' aggregation.py`
- On the fork: `grep -n '^def standardize\|…\|"accuracy": round' enigmaeval/enigmaeval_eval.py` and `grep -n '^def _pil_to_base64_png\|…\|"all": list' enigmaeval/enigmaeval_utils.py`
- `grep -n 'generous max-output-token\|`all` (default, 1161' README.md` and `grep -n 'max_tokens\|reasoning_effort\|temperature' configs/models.yaml`
- On the card and tips: `grep -n 'exact prompt construction\|…' card README.md` and `grep -n 'in the dark' standard_tips.txt`

## Recommended paid runs

1. **A paired run to bound D1 and D2.** Run one Candidate twice on the same Cases:
   - through the authors' harness unchanged, with `--model <m> --models_config` set to our Candidate's settings, a real system message and their reasoning fallback;
   - through our Engine.

   Compare the marks Case by Case. The room left under tolerance is 0.005 − 0.0026 = 0.0024 of the headline, about 3 Cases of 1,158, and EnigmaEval's correct marks are rare. So only a full 1,158-Case pair can show that D1 + D2 stay under 3 Cases. A subset can only show that they don't. A reasoning model at high effort is the useful choice, because it is the case where empty reply text happens.
2. **A free partial bound for D2**, before any paid run: in any real `enigmaeval` Report, count the Cases whose reply text is empty. That count caps the Cases D2 can move.

## Upstream notes

- **The paper disagrees with the harness.** The harness wins, and this is not counted in our bound.
  - The paper evaluates the first release: 1,184 puzzles, 949 normal and 235 hard (`paper:` §2, Table 1). v2 has 1,161, and the card says ids are not stable across versions (`card:README.md:56`).
  - The paper asks for the answer as `Answer: <answer>` (`paper:` Appendix B.2, B.4). The harness uses `<answer>…</answer>` tags.
  - The paper reports normal and hard separately, at the default temperature, averaged over 3 runs (`paper:` §3.1, Table 2 caption). The harness reports one pooled "Overall accuracy" from one run.
  - The paper strips the image tips for fully text puzzles (`paper:` Appendix B.2). The harness loads `imageless_tips.txt` (`fork:enigmaeval/enigmaeval_utils.py:229`) but never uses it.

  Bound of ours against the paper's Table 2: `unbounded` (a different puzzle set and answer format). The 7.0% / 0.0% cannot sit beside our headline.
- **The dataset card disagrees with the harness.** The card calls its builder "the exact prompt construction used for the reference runs" (gemini-3.1-pro, gemini-3.5-flash, gpt-5.5; `card:README.md:88`). Against the harness it differs as follows:
  - the picture sentence goes on `images_count > 0` (`card:README.md:158,174`) rather than on `[image_1]` in the text (`fork:enigmaeval/enigmaeval_utils.py:261`): 20 Cases;
  - it shows only the standard tips, where the harness gives MIT Mystery Hunt puzzles their own: 68 Cases;
  - 83 Cases in all, beyond whitespace;
  - on every Case it has no trailing newline after the answer-format line, and straight quotes in the tips (`card:README.md:100`) where the file has curly ones (`fork:enigmaeval/prompt_templates/standard_tips.txt:3`).

  Ours follows the harness by owner ruling (`enigmaeval.py:65-69`). If the dashboard's v2 numbers were made with the card's builder, the bound against them is `unbounded` (Candidate behaviour). No such number was found.
- **Harness quirks we share, so they are not deviations:**
  - the five `|` golds put spaces around `|`, so the gold as written, unsplit, fails its own check;
  - `standardize` drops non-ASCII letters (`BEYONCÉ` → `beyonc`);
  - a comma gold compares as a set of its parts (69 golds).

  The answer sheets mark all of these identically on both sides.
- **The harness's `requirements/base.txt` omits `litellm`**, which `fork:shared/llm_agents.py:13` imports. It was installed by hand. Cosmetic.
- **The CAIS private-dataset predecessor differs.** `cais-private:enigmaeval_eval.py:59-120` retries a failed call 3 times and reads `response.content` only, with no reasoning fallback. It is not the row's reference and is recorded for context only.
- **The harness reads the dataset unpinned and shuffles it** (`fork:enigmaeval/enigmaeval_utils.py:152-156`). HEAD equals our pin today. A later push to `cais/EnigmaEval` would move their puzzle set but not ours. `--num_puzzles` subsets follow the shuffled order, which does not matter for a full run.
- **inspect_evals** has no EnigmaEval at v0.20.0 (Checks run 18), so there is no `comparable-to-inspect` reference.
