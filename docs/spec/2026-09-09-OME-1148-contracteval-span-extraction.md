# OME-1148 — ContractEval as a deterministic clause-extraction benchmark

**Ticket:** [OME-1148](https://linear.app/openmined/issue/OME-1148/onboard-contracteval-as-a-deterministic-span-extraction-benchmark)
· **Ledger:** `docs/work/2026-09-09-OME-1148-contracteval-span-extraction.md`
· **Stack:** screamingface-engine, screamingface · **Date:** 2026-09-09

## 1. Problem

ContractEval (arXiv 2508.03080, NLLP 2025) grades clause-level legal extraction over the CUAD
test split. A Candidate receives a full commercial contract plus one clause-category question,
and must return the answering sentence(s) **verbatim** or the literal `"No related clause."`
Top reported model is GPT-4.1 at F1 **0.641** — far from saturated.

It is the cheapest board we could carry: grading spends **zero** tokens, like MedXpertQA. Unlike
MedXpertQA it is the first board whose headline number is not a per-case mean — F1 is computed
from a **dataset-level confusion matrix**, so the reducer must build one.

## 2. Established facts

Read from the reference harness (https://github.com/olivialiu121/ContractEval, MIT), not
inferred. Mirrored into `.refs/contracteval/` per the protocol-alignment rule.

**F-1 · The task is verbatim containment, NOT span overlap.** Our July screening notes
(`LiveTruth_leaderboard_work/docs/new-benchmarks.md`) recorded "F1/F2: how much do the returned
spans overlap the gold spans — partial credit for finding some but not all." That is **wrong**.
`proprietary_model.py` computes the per-row verdict as:

```python
if len(label) == 0:
    check_include.append(output.strip(" \n`").lower().startswith('no related clause'))
else:
    check_include.append(all(substr.strip(" \n`") in output.strip(" \n`") for substr in label))
```

All-or-nothing substring containment of **every** gold span. No partial credit, no token overlap,
no F1 at the case level. The per-case verdict is a boolean — structurally identical to
MedXpertQA's exact match.

**F-2 · F1/F2 are aggregate-level.** `Evaluation.py` builds a confusion matrix across rows:

```python
for classification, output, label in zip(check_include, outputs, labels):
    if len(label) == 0:
        tn += 1 if 'no related clause' in output.strip(" \n`").lower() else 0
        fp += 1 if not (...)                    # negative rows: abstain or be wrong
    else:
        tp += 1 if classification else 0        # positive rows: contain every gold span
        fn += 1 if not classification else 0
precision = tp/(tp+fp);  recall = tp/(tp+fn)
f1 = 2PR/(P+R);          f2 = 5PR/(4P+R)
```

Note the shape: **positive** rows can only be TP or FN; **negative** rows only TN or FP. So
precision mixes positive-row successes against negative-row failures. Unusual, but it is the
published metric and we reproduce it.

**F-3 · The abstain test is substring `in`, not `startswith`.** The empty-label branch of
`check_include` uses `.startswith(...)`, but `Evaluation.py` **ignores `classification` for
negative rows** and recomputes with `'no related clause' in output.strip(" \n`").lower()`. The
`startswith` variant never reaches a published number — dead code in the metric path. The
laziness counter also uses `in`.

**F-4 · Laziness divides by a hardcoded 1244 — which is the FULL split's positive count.**
`false_no_related_clause_rate = false_no_related_clause_cnt / 1244`. Measured directly off the
pinned parquet: the 4,182-row test split holds **exactly 1,244 positive rows** and 2,938
negatives (70.3%). The literal is therefore not tied to the paper's 4,128 figure at all — it is
`len(positive rows)` of the whole split, hardcoded.

**F-5 · Jaccard is secondary and positive-rows-only.** Not in `results.append`; merged in later
as a mean. Computed only where `len(label) != 0`, over `' '.join(label)` versus the output, with
this normalisation: strip `. , ; :`, lowercase, `/`→space, then `split(" ")` into a set. That
split yields **empty-string tokens**, which inflate the union — a quirk we mirror byte-for-byte.

**F-6 · The dataset is loadable after all — verified by loading it.** CUAD's HF `main` holds only `cuad-qa.py` (script
loader, viewer disabled) and `datasets==5.0.0` in `Dockerfile.benchmark` dropped script loaders.
But the auto-converted parquet branch **exists**: `refs/convert/parquet` at commit
`d9c4ee0250ae2eb97bdb5b50773ab14ea62d0631`, carrying `default/test/0000.parquet` (2.6 MB).
Loaded successfully on `datasets 5.0.1` / `pyarrow 25.0.1` via
`hf://datasets/theatticusproject/cuad-qa@refs/convert/parquet/default/test/0000.parquet`,
returning 4,182 rows with the F-7 columns. The blocker is dissolved — we pin that revision.

**F-7 · Row shape.** `id`, `title`, `context`, `question`, `answers: {text: [...], answer_start:
[...]}`. Gold spans are `answers['text']`, a list; empty list = no clause exists.

**F-8 · Prompts, verbatim.** System prompt and user template are captured in
`proprietary_model.py` lines 18-32 and 74-80. `temperature=0`.

**F-9 · Count discrepancy, and what it is not.** HF test = 4,182 rows (verified: 102 contracts
× 41 questions); the paper reports 4,128 *evaluated data points*. The 54-row gap is NOT a
different answer key — the laziness denominator matches the full split exactly (F-4) — so it is
most likely rows that failed to produce a usable output in the paper's own runs, not rows
excluded from the benchmark.

**F-10 · Context sizes, tokenized.** Measured with `tiktoken cl100k_base` over all 4,182 rows:
min 185 · **p50 5,357** · p90 22,688 · p99 54,172 · **max 63,389** tokens. 246 rows (5.88%, from
6 of the 102 contracts) exceed 32k; **zero rows exceed 64k**. The p50 independently reproduces
the ~5,500 tok/call figure the cost model back-solved from the paper's own $50 GPT-4.1 total.

## 3. Decisions

**D-1 · The per-case grade is a boolean, method `containment`.** Score 1.0 when the row's
verdict is correct per F-1/F-3, else 0.0. Not `exact_match` — the check is substring containment,
and naming it `exact_match` would misdescribe it in every report.

**D-2 · F1 is the headline `score`; the rest are `metrics`.** The reducer builds the confusion
matrix over graded cases and publishes `score = f1`, with `accuracy`, `precision`, `recall`,
`f2`, `no_related_clause_rate`, `false_no_related_clause_rate`, `jaccard_mean` as metrics. This
matches the paper's headline and keeps every secondary number visible.

**D-3 · Laziness uses the actual positive-row count of the selection, not 1244.** A hardcoded
denominator is wrong for any `limit=N` run and silently wrong for our 4,182-row selection. We
divide by the positive rows actually selected and record the deviation in the board docstring.
This is strictly safer at **no** cost to comparability: at the full split our denominator is
1,244 — identical to the literal (F-4) — and on a subset it is the only correct choice.

**D-4 · Reproduce all four reference quirks exactly** — substring `in` for abstain (F-3),
`split(" ")` empty tokens in Jaccard (F-5), Jaccard over positive rows only (F-5), and the
`.strip(" \n`")` applied to both sides everywhere. Each gets a test naming it as
protocol-alignment, so a future "cleanup" cannot silently move our scores off the paper's.

**D-5 · An unanswered or unparseable reply scores 0.0, not withheld.** Same rule as MedXpertQA:
a model that emits nothing usable has answered badly, not failed to run. `failure_policy` stays
`coverage_declare` for cases that never got a valid grade.

**D-6 · Selection is the full 4,182-row test split; the 4,128 gap is documented, not chased.**
The paper does not say which rows it dropped, so any reconstruction would be a guess. We publish
our own row count in the audit summary; `case_count` is what we bake.

**D-7 · No truncation. A prepare-time context guard instead.** The spec originally assumed a
head-anchored truncation rule; the measurement in F-10 removes the need. The largest contract is
63,389 tokens and every panel model carries ≥128k, so a truncation path would be dead code that
could only ever degrade comparability. `pins.py` instead pins `MAX_CONTEXT_TOKENS = 120_000` as a
**guard**: `prepare.py` raises `BenchmarkAssetPreparationError` if any row exceeds it, matching
HealthBench's "refuse to bake a different answer key" idiom. On the pinned revision it never
fires; if a future revision grows a document past the budget, the build fails loudly instead of
silently scoring a model against text it never saw.

**D-8 · `interaction="single_shot"`, `expected_check_cost="free"`.** One Candidate call per case;
the check is pure string work.

## 4. Design

Board package mirrors `medxpert/` — the proven non-rubric path (`spine.RowReader`, **no**
`spine.CaseGrader`, which is rubric-shaped and takes `points: list[int]`).

```
contracteval/
  pins.py            dataset + revision + prompt/protocol revisions + truncation budget
  prompts.py         the paper's system prompt and user template, verbatim
  prepare.py         parquet → cases.json (public: context+question) + answers/<id>.json (private: gold spans)
  answering.py       normalisation shared by check and grading (.strip(" \n`"), casefold)
  grading.py         verdict(output, gold_spans) -> bool  ·  jaccard(gold, pred) -> float
  case_evaluation.py bind/decode the per-Case envelope (attempt_1 shape)
  definition.py      revision hash, the url4 expression, BenchmarkDeclaration
  runtime.py         cases data route, check endpoint, case-evaluation, aggregate
  aggregate.py       confusion matrix → F1/F2 + laziness + jaccard mean
```

The url4 expression is the single-shot shape, not MedXpertQA's two-turn: one `candidate()` call,
then `check`, then `case-evaluation` via `attempt_records_endpoint` (the object-shaped helper
added in OME-1126 — the array-shaped `case_evaluation_endpoint` is for rubric `iterate` fan-outs
and would fail here exactly as it did there).

`aggregate.py` is where this board is genuinely new. Every other reducer maps case scores to a
mean; this one must carry each case's (is_positive, is_correct, abstained) triple up to the
scorer to build TP/TN/FP/FN. That triple rides in the case grade's `metrics`.

## 5. Error handling

- Missing/invalid answer asset → `missing_answer_asset`, that Case fails, others score.
- No row for a selected Case → `missing_case_row`, with collected errors attached.
- Malformed check payload → `benchmark_unavailable` from the shared endpoint.
- A Case whose invocation errored is score `None` (not measured), never 0.0 — the
  failure-to-COMMIT vs failure-to-RUN invariant MedXpertQA established.

## 6. Consequences

- First board publishing a dataset-level F1. The scoreboard shows `score`; readers comparing to
  the paper get the same number.
- No truncation path exists, so no case can be scored against text the model could not see; the
  context guard converts that risk into a build failure (D-7).
- Laziness is a refusal signal and may favour panels. Neutral board: we publish it because the
  paper does, not as a fusion-win argument.

## 7. Test plan

- `grading.py`: every branch of F-1 — all gold spans present, one missing, none present, empty
  gold + abstain, empty gold + answer. Substring-not-token semantics pinned explicitly.
- Abstain detection: `in` not `startswith` (F-3), case-insensitivity, backtick/newline stripping.
- Jaccard: a worked example reproducing the reference's empty-token union inflation (F-5).
- `aggregate.py`: confusion matrix over a mixed set; F1/F2 arithmetic against hand-computed
  values; laziness denominator = selected positives (D-3); Jaccard mean skips negatives.
- Unanswered case scores 0.0 and stays in the denominator (D-5); errored case scores `None`.
- `prepare.py`: parquet pin, public/private split, gold-span list validation, and the context
  guard both ways — passes on the pinned revision, raises on a synthetic over-budget row.
- Declaration guard tests updated for the new board (both are full-strength tables).

## 8. Out of scope

- FS-Research and the repeats/epochs protocol it needs — separate epic.
- Reconstructing the paper's 4,128-row subset (D-6).
- Any span-overlap or partial-credit grader — the protocol has none (F-1).
