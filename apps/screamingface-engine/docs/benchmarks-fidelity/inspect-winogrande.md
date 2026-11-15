---
benchmark: inspect-winogrande
origin: inspect_evals
verdict: unverified
verdict_reason: "Two possibly-score-changing deviations are open, and only a run can size either of them. D1: our Case now carries inspect_evals' 5 worked examples, the same 848 characters inspect sends, but they reach the Candidate as leading user text, while inspect sends them as a separate system turn. The text is byte-equal on 1267/1267 Cases (inspect's system text, a blank line, then inspect's user text). Only the role differs. Nothing on the row declares this fold as a Named Deviation. D2: the Task fixes GenerateConfig(max_tokens=64), and our Benchmark does not apply it. inspect's real eval() was shown sending max_tokens 64 on every model call. The other checks all match inspect_evals' default winogrande(): dataset and digests reproduce, 19 answer sheets x 1,267 Cases give 0 differing marks, and the headline equals accuracy() to four decimals on every vector. The one other deviation is cosmetic (no stderr). The paper's numbers come from finetuned classifiers, a different process by design, so the reachable verdict is comparable-to-inspect once D1 and D2 are sized."
audited: 2026-11-10
audited_at: b245a641b
fingerprint:
  benchmark: 3f2af135ba8bad37
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/winogrande
references:
  paper: https://arxiv.org/abs/1907.10641v2
  original_harness: https://github.com/allenai/winogrande/tree/727e837f77521ef38bcc56df3b275c8da43f45af
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No test puts inspect_evals' marks or the authors' marks beside ours on the real Cases. The closest pins are tests/unit/inspect/test_benchmark_fingerprints.py:70 and tests/unit/inspect/test_published_revisions.py:84 (both 3f2af135ba8bad37, 1 passed each), and tests/unit/inspect/test_inspect_imported_benchmarks.py:71 (winogrande in the mcq family, 6 passed with -k winogrande). The parity evidence is the answer sheets in this record: 19 sheets x 1,267 Cases = 24,073 marks per examiner, 0 differing."
---

# WinoGrande — Fidelity Record

## Verdict

**`unverified`.** Our headline is plain accuracy over the 1,267 [WinoGrande](https://github.com/allenai/winogrande/tree/727e837f77521ef38bcc56df3b275c8da43f45af) XL validation sentences. They are graded by inspect's `choice()`, the scorer of [inspect_evals v0.20.0 `winogrande`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/winogrande). Since OME-1860 the row calls the Task with inspect_evals' defaults (`fewshot=5`). The zero-shot gap the last record found is closed: each Case now opens with the same 5 worked examples inspect sends.

**Two differences stay open, and only a run can size them:**

- **D1, the worked examples arrive in a different role.** inspect sends them as a system turn. We fold them into the Case as leading user text, followed by a blank line and then the question (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:79`, `:538`). The text is equal on 1267/1267 Cases, but nothing on the row declares the fold as a Named Deviation.
- **D2, inspect_evals' 64-token reply cap is not applied** (`inspect_evals:winogrande/winogrande.py:101`). Our Benchmark has no generation-settings field, so nothing applies it.

Both are `possibly-score-changing` with bound `unknown`. Everything else matches the default `winogrande()`:

- Prompt text, targets and choices are equal on 1267/1267 Cases.
- All 19 answer sheets give 0 differing marks.
- The headline equals inspect's `accuracy()` to four decimals on 5 fixed vectors and on all 19 sheet vectors.
- The only other difference is D3: inspect's `stderr` is not published (cosmetic).

The arithmetic:
- Bounds against inspect_evals' default run: D1 `unknown` + D2 `unknown` + D3 `0`. An open `possibly-score-changing` deviation means **`unverified`**.
- On the checked dimensions alone: `0/1267 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)` on prompt text, extraction, metric and roll-up.
- For D1 + D2 combined, a sizing run fits the tolerance if it shows at most 6 differing Cases (`6/1267 = 0.0047`). Seven do not (`7/1267 = 0.0055`).

`comparable-to-paper` is out of reach by design. [Sakaguchi et al. 2019](https://arxiv.org/abs/1907.10641v2) report finetuned classifiers (RoBERTa 79.3 dev / 79.1 test, Table 3), not a prompted number. inspect_evals vs the authors' harness is therefore `unbounded` (Upstream notes). Once D1 and D2 are sized within tolerance, this row reads **`comparable-to-inspect`**.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Our production replay** of `replay_with_provenance(TASK_REPLAY_CASES["winogrande"])` in a clean environment (Checks 3):<br>• `replay: 1267 Cases in 57.8 s`<br>• `case_count pinned 1267 equal True`<br>• `case_digest computed 6dc17beb2ae9078b pinned 6dc17beb2ae9078b equal True`<br>• `case_set_digest computed ee527fabcbce6374 pinned ee527fabcbce6374 equal True`<br>Pins: `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:781-784`. Provenance: one source, `hugging-face allenai/winogrande/winogrande_xl`, `revision 01e74176c63542e6b0bcb004dcdea22d94fb67b5`, `seeds_applied {}`, `samples {'yielded': 1267, 'excluded': 0, 'kept': 1267}`.<br>**Theirs:** `WINOGRANDE_DATASET_REVISION = "01e74176…"` (`inspect_evals:winogrande/winogrande.py:38`), `split="validation"` (`:82`), `shuffle: bool = False` (`:68`), `filter_duplicate_ids` (`:90`); `eval.yaml:11` `dataset_samples: 1267`.<br>**Against inspect's `winogrande()` Samples:** `target != inspect Sample.target [] count 0`, `choices != inspect Sample.choices [] count 0`, `sample ids equal default vs fewshot=0 True unique 1267`; targets `B 639, A 628`.<br>**The worked examples** come from the `train` split at the same pinned revision (`winogrande.py:113-122`; `fewshot_seed` 42, `inspect_evals:constants.py:39`). They are frozen into each Case's text and sealed by the Case Digest. Provenance lists one source entry, since both reads share location and pin.<br>**Against the authors' `winogrande_1.1/dev.jsonl`** (1,267 rows, sha256 `1aeac79cf46a3dcb`), order-aligned (Checks 5): `question block differs [] 0 \| options differ [] 0 \| answer differs [] 0`. |
| prompt | deviation | possibly-score-changing | unknown | **D1: the text is equal and the role differs.** inspect's default `winogrande()` was run on all 1,267 Samples through its own solver chain with a recording stub `generate` (Checks 3):<br>• `[default] message roles {('system', 'user'): 1267}`<br>• `distinct system-message tuples across Cases 1`; `system message chars 848 sha256 3417cecef1199e14 'ANSWER:' lines 5`<br>• `Cases where our input != inspect system text + blank line + inspect user text: [] count 0`<br>• `Cases where our input == inspect user text alone (no system): 0`<br>• `Cases where default user message != fewshot=0 user message: 0`<br>inspect's real `eval()` on `mockllm/model` (no provider, no key, Checks 4) shows the model receives `model event roles ['system', 'user']` on each of 3 Samples.<br>**Where the text comes from:** the system text is `SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE` (`inspect_evals:winogrande/winogrande.py:47-50`), inserted by `system_message` (`:128-137`; `inspect_ai:solver/_prompt.py:46`, `:70`). The user text is `USER_PROMPT_TEMPLATE` (`winogrande.py:53-56`) applied by `multiple_choice` (`:110`).<br>**Ours:** the joined text is one Case input, `_MESSAGE_SEPARATOR.join(...)` (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:79`, `:538`). sha256 of all our inputs: `ba74ace9572e73da`. |
| answer extraction | match | — | — | **Same functions on both sides.** Ours calls inspect's own `set_choices_based_on_generated_response(state, parse_answers(state, multiple_correct))` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`) with `multiple_correct False` (Checks 2). inspect's solver runs the same pair after `generate` (`inspect_ai:solver/_multiple_choice.py:332`; `parse_answers` `:82`, strict regex `:99`, lenient `:108`; `set_choices_based_on_generated_response` `:155`).<br>**Answer sheets** (Checks 3): 19 sheets × 1,267 Cases = `marks per examiner: 24073`. Ours goes through the installed Benchmark's aggregate route. Theirs is the default `winogrande()` solver chain (stub `generate` returning the reply), then `choice()`. Every sheet: `differing 0 []`.<br>One sheet is new for the 5-shot prompt: `fewshot_echo_then_gold` repeats the Case's sentence and option lines in the worked-example format, then `ANSWER: X`. It scores 1267 on both sides.<br>No recorded replies exist: `ls tests/unit/inspect/goldens` → no such directory, and `grep -rli winogrande tests` lists only declaration, fingerprint, revision and failure-policy test files. |
| metric | match | — | — | **Same scorer.** The row's scorer is `inspect_ai.scorer:choice` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:829`), built by `_scorer_factory` (`benchmarks.py:8484`). That is the Task's own `scorer=choice()` (`inspect_evals:winogrande/winogrande.py:100`; `inspect_ai:scorer/_choice.py:60-61`). `C`/`I` map to 1.0/0.0 (`scorer_adapter.py:111`; `inspect_ai:scorer/_metric.py:279`).<br>**Per-sheet sums, ours = inspect (Checks 3):**<br>• **1267 each:** `ANSWER: X`, `ANSWER: X.`, reasoning then `ANSWER: X`, `ANSWER: x`, `ANSWER: X,`, `ANSWER: X) <option>`, wrong line then gold line, the few-shot echo then gold.<br>• **0 each:** `**ANSWER:** X`, `ANSWER: (X)`, `(X)`, bare `X`, `The answer is X.`, the option text, `ANSWER: <wrong>`, `ANSWER: A, B`, gold line then wrong line, empty, `I am not sure.`<br>All 19 sheets: `differing 0`, `failures []`. `test_inspect_imported_benchmarks.py -k winogrande`: 6 passed (Checks 6). |
| roll-up | deviation | cosmetic | 0 | **The headline is equal. D3 is the unpublished `stderr`.** Ours is `_accuracy`, `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `:1303`), with `whole_run_metric_factory None` (Checks 2). Theirs is `accuracy()`, `total / float(len(scores))` (`inspect_ai:scorer/_metrics/accuracy.py:15`, `:37`), from `@scorer(metrics=[accuracy(), stderr()])` (`inspect_ai:scorer/_choice.py:60`).<br>**Fixed vectors** (Checks 3), each first asserted to equal our per-Case marks: all-1 `1.0`, all-0 `0.0`, alternating `0.5004`, every-3rd `0.3339`, first-50 `0.0395`. All `equal4 True`, and the 19 sheet vectors are also `equal4 True`.<br>Our metrics are `{'correct': 634, 'scored_cases': 1267}` on the alternating vector, with no stderr (inspect's is `0.0141`).<br>**The authors roll up the same way:** `simple_accuracy` = `(preds == labels).mean()` (`fork:scripts/utils.py:467-468`), and the data zip's `eval.py:37` uses `accuracy_score`. |
| judge | not applicable | — | — | `imported_benchmark("winogrande").judge` → `None` (Checks 2). The Task's only scorer is `choice()` (`inspect_evals:winogrande/winogrande.py:100`), which calls no model. |
| sampling | deviation | possibly-score-changing | unknown | **D2.** inspect_evals sets `config=GenerateConfig(max_tokens=64)` (`inspect_evals:winogrande/winogrande.py:101`). The built Task printed `task.config max_tokens=64 temperature=None epochs=None`. The solver's own call carried `{"max_tokens": null}` (`inspect_ai:solver/_multiple_choice.py:332`), and `merge` skips `None` values (`inspect_ai:model/_generate_config.py:389-391`). That merge runs after the Task config loads (`inspect_ai:_eval/task/run.py:768`). inspect's real `eval()` on `mockllm/model` confirmed it: `config max_tokens 64 temperature None` on each model event (Checks 4).<br>**Ours:** `BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='easy', attempts=1)` (Checks 2). `BenchmarkSpec` and `Benchmark` have no generation-settings field. `grep -rn "task.config\|\.config\.max_tokens\|GenerateConfig" src/` finds no reader of the Task's config on the import or run path; the one comment is the math row's "the importer never reads task.config" (`benchmarks.py:4191`).<br>Attempts are 1 on both sides. Temperature is left open by both. |

## Deviations

### D1 — the worked examples reach the Candidate as user text, not a system turn

- **Declared?** Not on the row, though it is declared at the plugin level. That makes it a finding.
  - **What the row has:** no `# NAMED DEVIATION` line (`awk` over `benchmarks.py:807-866` and `prepare.py:771-790`, Checks 7). No `named_deviations/` scorer, `dropped_scorers ()`, `excluded_sample_ids None` (Checks 2), and no linked README.
  - **What comes close:**
    - The `prepare.py` comment says "Cases carry inspect_evals' default 5 worked examples, the system message capture folds ahead of the question" (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:773-774`). A comment is not a declaration form.
    - The description says "each preceded by inspect_evals' 5 worked examples" (`benchmarks.py:814`) but not that they arrive as user text.
    - The plugin-wide constant calls the fold a "Named deviation (contracteval pattern)" (`capture.py:76-79`). The glossary lists "a system message delivered as input text" as a Named Deviation example (`CONTEXT.md:323-326`).
  - **Same situation elsewhere:** this matches the cybermetric rows. A one-line `# NAMED DEVIATION` on the row would make D1 declared, and it would still count in the bound.
- **Where.**
  - Theirs: `system_message(SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE.format(...))` inserted at index 0 of the solver chain (`inspect_evals:winogrande/winogrande.py:128-137`), producing a `ChatMessageSystem` (`inspect_ai:solver/_prompt.py:70`).
  - Ours: `_MESSAGE_SEPARATOR = "\n\n"` (`capture.py:79`) joins the system text and the user text into one Case input (`capture.py:538`), which is sent as the user turn. The grader gets it the same way (`scorer_adapter.py:635`).
- **What differs.** Only the role, on all 1,267 Cases. The text is byte-equal: `Cases where our input != inspect system text + blank line + inspect user text: [] count 0`. The system text ends in `\n`, so our input has three newlines between `ANSWER: B` (the last example) and `Answer the following…`. That is exactly inspect's text joined by our blank line.
- **Severity / bound.** `possibly-score-changing`, `unknown`. Whether a Candidate answers differently when examples come as a system turn rather than user text depends on the Candidate. Only a paired run can count the Cases that flip.
- **Evidence.** Checks 3: `[default] message roles {('system', 'user'): 1267}`, `… [] count 0`, `Cases where our input startswith system text: 1267`. Checks 4: `model event roles ['system', 'user']` under inspect's real `eval()`.

### D2 — inspect_evals' 64-token reply cap is not applied

- **Declared?** No. The row has no `# NAMED DEVIATION` line, and its description is silent on generation settings (`benchmarks.py:811-821`). The math row declares the same importer behaviour in a comment (`benchmarks.py:4190-4192`); this row does not.
- **Where.**
  - Theirs: `config=GenerateConfig(max_tokens=64)` (`inspect_evals:winogrande/winogrande.py:101`), merged into every generate call (`inspect_ai:_eval/task/run.py:768`).
  - Ours: no generation-settings field exists on the row or on `Benchmark`, and no source reads `task.config` (Checks 7).
- **What differs.** Under `inspect eval` the Candidate's reply stops at 64 output tokens. A Candidate that reasons for more than 64 tokens before `ANSWER: X` loses the answer line and is marked wrong. Under ours the same reply is credited. The cap can only lower inspect's score relative to ours. The 5 worked examples now model a bare `ANSWER: X` reply, which may make long replies rarer, but that is the Candidate's behaviour, not something this audit can measure.
- **Severity / bound.** `possibly-score-changing`, `unknown`. The affected Cases are those whose reply runs past 64 tokens with the answer after the cut, and a run's Report reveals them. No Report exists on this revision: the commit message records "no leaderboard scores yet".
- **Evidence.** Checks 3: `task.config max_tokens=64`, `generate kwargs seen ['{"max_tokens": null}']`. Checks 4: `config max_tokens 64 temperature None` on all 3 model events.

### D3 — inspect's standard error is not published

- **Declared?** No. The description says "Benchmark score = plain accuracy over the cases run" (`benchmarks.py:818`) and is silent on stderr. It is an undeclared, cosmetic finding.
- **Where.** Ours: `_accuracy` publishes the mean, `correct` and `scored_cases` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275-1303`). Theirs: `choice` carries `metrics=[accuracy(), stderr()]` (`inspect_ai:scorer/_choice.py:60`).
- **What differs.** The reported uncertainty, not the headline.
- **Severity / bound.** `cosmetic`, `0`. Checks 3 roll-up: `equal4 True` on every vector.

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` was empty before and after, and `git rev-parse --short HEAD` was `b245a641b` both times. `find . -newer <first scratch script> -not -path "./.git/*"` listed nothing, so the test runs wrote no file into the checkout. Every file lived under `SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-inspect-winogrande-VfCg`, created with `mktemp -d`, with `TMPDIR`, `XDG_CACHE_HOME`, `INSPECT_EVALS_CACHE_DIR` and `HF_HOME` pointed inside it. It was deleted at the end with `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])"`, and `ls` then gave `No such file or directory`.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` printed nothing (`grep exit=1`). Every third-party command ran under that prefix: `uv run --isolated --extra inspect`, `git clone`, `curl`. Inside each audit process, `env key/token/secret []`. No model, gateway or provider was called. Replies were hand-written strings passed to `ModelOutput.from_content` by a stub `generate`. The one `eval()` used inspect's built-in `mockllm/model`, which makes no network call.
- [x] **Harness over paper.** The authors' repository holds the data, a RoBERTa multiple-choice finetuning script and an accuracy script. The paper's Table 3 numbers come from that finetuned-classifier process, which differs from inspect_evals' prompted examiner by design (Upstream notes).
- [x] **Declared is not a finding.** No declared deviation exists on this row. D1 is declared only at the plugin level (`capture.py:76-79`), not by a row-level form, so it is a finding. D2 and D3 are undeclared.
- [x] **Every cell has evidence.** Each `match` names its command and output lines below.
- [x] **Every `file:line` is copied from command output.** Ours comes from `grep -n` / `awk` / `sed -n` on the checkout (Checks 7). `inspect_evals:` and `inspect_ai:` come from `cat -n` / `grep -n` on copies of the installed 0.20.0 / 0.3.263 files (Checks 1). `fork:` comes from `grep -n` on the allenai/winogrande clone and its data zip (Checks 5).
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. D1 and D2 are open `possibly-score-changing` deviations, so the verdict is `unverified`.
- No `ours` override was set.

1. **Reference copies.** `info.py` copied `inspect_evals/winogrande/`, `inspect_evals/constants.py` and inspect_ai's `scorer/_choice.py`, `solver/_multiple_choice.py`, `solver/_prompt.py`, `scorer/_metrics/accuracy.py`, `scorer/_metric.py`, `_eval/task/run.py` and `model/_generate_config.py` from the installed packages into scratch. It printed `versions 0.20.0 0.3.263`. The commands that gave the line numbers:
   - `cat -n inspect_evals/winogrande/winogrande.py` (169 lines): docstring `:9-14`; `:37-38`; `:41`; `:47-50`; `:53-56`; `def winogrande(` `:63`; `fewshot: int = 5` `:65`; `:66-68`; `:79-86`; `:90`; `:100`; `:101`; `winogrande_solver` `:107-139`; `:110`; `:112-122`; `:128-137`; `record_to_sample` `:142-155`; `sample_to_fewshot` `:158-169`.
   - `grep -n DEFAULT_FEWSHOT_SEED constants.py` → `:39`.
   - `grep -n` on `README.md` → `:22` plain run, `:46` `--temperature`, `:60-62` parameters. Its headers (`grep -n "^#"`) end with Dataset `:67`, Evaluation `:79`, Changelog `:83`, so there is no results section.
   - `cat -n eval.yaml` → `:3` description, `:8` `version: "2-A"`, `:11` `dataset_samples: 1267`.
   - inspect_ai via `grep -n`:
     - `scorer/_choice.py`: `:60`, `:61`
     - `solver/_multiple_choice.py`: `:82`, `:99`, `:108`, `:155`, `:247`, `:332`
     - `solver/_prompt.py`: `:46`, `:70`
     - `scorer/_metrics/accuracy.py`: `:15`, `:37`
     - `scorer/_metric.py`: `:279`
     - `_eval/task/run.py`: `:767-768`
     - `model/_generate_config.py`: `merge` `:373`, `if value is not None` `:391`
2. **Our declaration.** `env -i … uv run --isolated --extra inspect python -I info.py` from `apps/screamingface-engine` printed:
   - `fingerprint 3f2af135ba8bad37`, `benchmark id inspect-winogrande case_count 1267`, `row published_revision 3f2af135ba8bad37`, and `harness_url` equal to the front matter.
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='easy', attempts=1)`.
   - `judge None multiple_correct False inverted_grade False`, `whole_run_metric_factory None epoch_reducer_factory None named_scores () extra () envelope False`, `row dropped_scorers ()`.
   - `TaskReplayCasesSpec(task='inspect_evals.winogrande.winogrande:winogrande', case_count=1267, case_digest='6dc17beb…', task_args=None, …, excluded_sample_ids=None, license='cc-by-4.0', source_pins={'allenai/winogrande': '01e74176…'}, shuffle_seed=None, choice_shuffle_seed=None, …, case_set_digest='ee527fab…')`.
3. **The main audit.** `env -i PATH HOME=$SCRATCH UV_CACHE_DIR TMPDIR XDG_CACHE_HOME INSPECT_EVALS_CACHE_DIR HF_HOME HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I audit.py $SCRATCH` → `exit=0`. In order:
   - **Production replay:** the seal lines in the dataset row; `provenance pins {'inspect-ai': '0.3.263', 'inspect-evals': '0.20.0'}`; `input types ['str']`; `grading material keys ['choices', 'target']`; Case 1 `{'target': 'B', 'choices': ['Sarah', 'Maria']}`.
   - **inspect `winogrande()` (default) and `winogrande(fewshot=0)`:** each Sample went through `task.solver` on a `TaskState` built with inspect's own `sample_messages`, using a recording stub `generate`. Output:
     - the prompt-row lines
     - `[fewshot=0] message roles {('user',): 1267}`
     - `system message repr head "The following are multiple choice questions, … by A or B.\n\nSentence: The phone of Donald is a lot better than Adam's because [BLANK] paid e…"`
     - worked-example answers `['A', 'A', 'A', 'A', 'B']`
     - first ids `winogrande_b0d318de, winogrande_1070465e, winogrande_9e9279c5`
   - **Answer sheets:** 19 replies per Case (listed in the metric row).
     - Ours: `_write_cases` into a scratch bundle, `ib.benchmark.install(node, root)`, then `ib.aggregate_route` over graded-answer rows. This mirrors `_node`/`_row`/`_scores` in `tests/unit/inspect/test_inspect_task_replay_benchmarks.py:88`, `:116`, `:136`.
     - Theirs: the default `winogrande().solver` with a stub `generate` returning the reply, then `choice()` and `value_to_float()`.
     - Output: `marks per examiner: 24073`, and `differing 0 []` on all 19 sheets.
   - **Roll-up:** `roll-up alternating: ours 0.5004 inspect 0.5004 equal4 True | inspect stderr 0.0141`, with the other four fixed vectors and the 19 sheet vectors also `equal4 True`.
4. **inspect's real runtime:** `env -i … uv run --isolated --extra inspect python -I runtime.py $SCRATCH/logs` called `inspect_ai.eval(winogrande(), model="mockllm/model", limit=3)` and printed:
   - `status success plan config 64`
   - `sample winogrande_1070465e model event roles ['system', 'user'] config max_tokens 64 temperature None`, and the same for `winogrande_9e9279c5` and `winogrande_b0d318de`
5. **Original sources:**
   - **Authors' repository.** `env -i … git clone https://github.com/allenai/winogrande harness` → `727e837f77521ef38bcc56df3b275c8da43f45af 2020-03-13 Merge pull request #3 from allenai/dev_superglue`. `sed -n 3p download_winogrande.sh` → the `winogrande_1.1.zip` URL.
   - **Data zip.** `env -i … curl -sSL` of that zip → sha256 `3619ab104d8be2977b25c90ff420cb42d491707dcc75362a1e5d22bc082b7318`. `wc -l` → `1267 dev.jsonl`, `1267 dev-labels.lst`. `dev.jsonl` sha256 `1aeac79cf46a3dcbe59a71ca7e5372a1490cde2b4ae2387dc56f00378104d2e8`.
   - **Order-aligned comparison.** `python3 -I authors.py` compared our sealed bundle with the authors' file. It checked that each Case input ends with a blank line plus `Sentence: <sentence with _ → [BLANK]>\nA) …\nB) …\n`, that the `choices` match `[option1, option2]`, and that the target matches `answer` mapped 1→A, 2→B. Output: `question block differs [] 0 | options differ [] 0 | answer differs [] 0`; `authors qIDs unique 1267 sentences unique 1267`.
   - **Harness line numbers.** `grep -n` gave `fork:scripts/utils.py:136` (`WinograndeProcessor`), `:144` (`dev.jsonl`), `:173-174` (`_` replaced by each option), `:467-468` (`simple_accuracy`); `fork:scripts/run_experiment.py:270` (`np.argmax(preds, axis=1)`); `fork:scripts/roberta_mc.py:7` (`RobertaForMultipleChoice`); `winogrande_1.1/eval.py:37` (`accuracy_score`); `fork:README.md:21` (test labels not included).
   - **Paper.** `env -i … curl -sL https://arxiv.org/abs/1907.10641` → "this version, v2", "last revised 21 Nov 2019". `curl -sL https://arxiv.org/pdf/1907.10641v2` then `pdftotext -layout` gave 593 lines: `:335` "The best model, RoBERTa, achieves 79.1% test-set accu-", `:350` RoBERTa `79.3` / `79.1`, `:358` Human Perf. `94.1` / `94.0`.
6. **Named tests.** Each ran as `env -i … uv run --isolated --extra inspect pytest <file> -q -p no:cacheprovider -k winogrande`:
   - `tests/unit/inspect/test_benchmark_fingerprints.py` → `1 passed, 94 deselected`
   - `tests/unit/inspect/test_published_revisions.py` → `1 passed, 92 deselected`
   - `tests/unit/inspect/test_inspect_imported_benchmarks.py` → `6 passed, 558 deselected, 1 warning`
   - `grep -n '"winogrande"'` on the three files → `test_benchmark_fingerprints.py:70`, `test_published_revisions.py:84`, `test_inspect_imported_benchmarks.py:71`.
7. **Our side, citations.**
   - `awk 'NR>=807 && NR<=866 && /key=|published_revision|failure_policy|scorer=|harness_url|human_baseline|Frontier score|score=0.885|Benchmark score|worked|inspect_evals_case_count/' benchmarks.py` → `808`, `809`, `814`, `818`, `826`, `829`, `848`, `855`, `856`, `859`, `865`.
   - `awk 'NR>=807 && NR<=866 && /max_tokens|temperature|params|attempts|NAMED DEVIATION|Named Deviation|excluded|dropped|fewshot|shot|config|worked|system/'` → only `814` (description, "5 worked examples") and `856` (Frontier Score comment, "5-shot").
   - `awk 'NR>=771 && NR<=789 && /NAMED|fewshot|task_args|Fold|system|worked/' prepare.py` → only `773-774`, the Task-args comment. There is no `task_args` and no `NAMED DEVIATION`.
   - `grep -n "task.config\|never reads" benchmarks.py` → `4191`. `grep -rn "task.config\|\.config\.max_tokens\|GenerateConfig" src/` → no reader of the Task config. `grep -n "params" benchmarks.py` → only `JudgeSpec` params.
   - `grep -n "Named deviation\|_MESSAGE_SEPARATOR" capture.py` → `76`, `79`, `538`, `553`.
   - `grep -n "def _accuracy\|score=round(sum(values) / len(cases), 4)" single_shot.py` → `1275`, `1303`.
   - `grep -n "set_choices_based_on_generated_response(\|_INSPECT_LETTER_SCORE_VALUES\|ChatMessageUser(" scorer_adapter.py` → `111`, `635`, `651`. `grep -n "def _scorer_factory" benchmarks.py` → `8484`.
   - `grep -n "Named Deviation" -A 8 CONTEXT.md` → `323-326`. `grep -n "^| D2\|^| D3" docs/spec/2026-10-02-ome-1460-one-fetch-path.md` → `282`, `283`.

## Recommended paid runs

**One Candidate, three runs, no judge (the scorer is deterministic).** This sizes D1 and D2 together. Use the same Candidate at temperature 0, on all 1,267 Cases each time:

- **(a)** Our Benchmark as served.
- **(b)** `inspect eval inspect_evals/winogrande --model <same>`: the default 5-shot run, 64-token cap.
- **(c)** The same as (b) with `--max-tokens` raised to the Candidate's own limit. The CLI value merges over the Task's (`inspect_ai:_eval/task/run.py:768`).

Reading the results:

- (a) vs (c) counts the Cases whose mark flips on D1 (system turn vs leading user text).
- (b) vs (c) counts the Cases the 64-token cap cuts off (D2).
- Run-to-run noise on the provider counts against the bound, so a repeat of (a) shows the noise floor.
- The verdict moves to `comparable-to-inspect` if the D1 + D2 differences total at most 6 Cases (`6/1267 = 0.0047 ≤ 0.005`).
- The result holds for that Candidate only.

**Cheaper first look at D2 (free once a Report exists).** No Leaderboard run exists on revision `3f2af135ba8bad37` yet. From the first one, count the Cases whose reply exceeds 64 output tokens and whose `ANSWER:` line falls after token 64.

**Owner calls (not made here).**

- **D1:** a `# NAMED DEVIATION` line on the winogrande row naming the fold would make it declared, as `capture.py:76-79` already does at the plugin level. It would still count in the bound until (a) vs (c) sizes it.
- **D2:** the row has no field to apply `max_tokens=64`. Declaring it as a Named Deviation (as the math row does at `benchmarks.py:4190-4192`) is the available option.

## Upstream notes

- **inspect_evals vs the authors' harness: a different process by design, `unbounded`.** The paper's numbers come from finetuned classifiers. RoBERTa-large, finetuned on the XL training set, scores both filled-in sentences (`fork:scripts/utils.py:173-174`, `fork:scripts/roberta_mc.py:7`) and takes the argmax (`fork:scripts/run_experiment.py:270`). That gives 79.3% dev / 79.1% test ([arXiv 1907.10641v2](https://arxiv.org/abs/1907.10641v2), Table 3). inspect_evals instead prompts an off-the-shelf model, 5-shot by default, to write `ANSWER: A|B` (`inspect_evals:winogrande/winogrande.py:47-56`).
  - The paper has no prompted number to compare with.
  - The data agree exactly: the 1,267 dev rows match in sentence, options, answer and order (dataset row).
  - The whole-run metric is the same plain mean (`fork:scripts/utils.py:467-468`).
  - So the gap is the examiner, not the exam.
- **The paper's test numbers come from a hidden split.** Test labels are not released (`fork:README.md:21`). Our Cases are the 1,267-row dev split. The row's human baseline `0.94` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:855`) is the paper's test-set figure (94.0, rounded); the dev-set figure is 94.1. This is a provenance matter, outside the seven dimensions.
- **inspect_evals' default worked examples lean towards A.** The 5 examples seeded by `fewshot_seed=42` answer A, A, A, A, B (Checks 3). Since OME-1860 that is the exam we serve, and it is also inspect_evals' default. It is not a deviation of ours.
- **inspect_evals' `eval.yaml` describes a different dataset.** `eval.yaml:3` reads "Set of 273 expert-crafted pronoun resolution problems". That describes the original WSC, not WinoGrande's 1,267 dev rows (`eval.yaml:11`). Cosmetic metadata, worth filing with [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals).
- **No published inspect_evals number.** The eval's README has no results section (headers end with Dataset `:67`, Evaluation `:79`, Changelog `:83`). Here, "comparable to inspect_evals" can only mean comparable to a run of the pinned eval, which is what the recommended runs produce.
- **Reviewer note, outside the seven dimensions.** The row's Frontier Score is `0.885`, Claude 3 Opus, "accuracy, 5-shot" (`benchmarks.py:856-859`). It is a vendor number from the vendor's own 5-shot prompt. Our exam is now 5-shot too, but with inspect_evals' examples and template, so the two numbers come from different prompts.
