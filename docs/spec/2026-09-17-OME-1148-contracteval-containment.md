# OME-1148 — ContractEval as a judge-free clause-containment board

**Ticket:** [OME-1148](https://linear.app/openmined/issue/OME-1148/onboard-contracteval-as-a-judge-free-clause-extraction-benchmark)
· **Ledger:** `docs/work/2026-09-17-OME-1148-contracteval-containment.md`
· **Stack:** screamingface-engine, screamingface · **Date:** 2026-09-09, §4 rewritten 2026-09-17

> **Rebuild note.** §2 (facts) and §3 (decisions) are unchanged — they describe ContractEval and
> CUAD, not our infrastructure. Only §4 Design is rewritten: the first implementation (tag
> `OME-1148-v1-pre-overhaul`) predates the spine overhaul that replaced `CaseGrader` with the
> `grade_case` seam.

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
inferred.

AMENDED 2026-09-18 (review of PR #984): this previously promised the harness was "mirrored into
`.refs/contracteval/`". It never was — the vendoring was dropped during implementation because
`.refs/` is not a repo convention and the upstream analysis scripts import matplotlib, so an
unexcluded copy fails this stack's gates. The promise outlived the decision, which left the
fidelity claim resting on nothing. The four functions the metric path depends on are now
committed verbatim as test material in `tests/unit/_contracteval_reference.py`, and
`test_contracteval_parity.py` proves ours equal them over 120 real CUAD rows.

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

**F-8 · Prompts, verbatim.** System prompt is `proprietary_model.py` lines **75-79**; the user
template is lines **19-27**. `temperature=0`. (Line ranges corrected 2026-09-18 — this said
18-32/74-80 while `prompts.py` said 74-80/18-27, and neither matched the file. Verified against
the source; `test_contracteval_prompts.py` now pins the bytes, which is the check that actually
protects the exam.)

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

**D-3 · Laziness divides by the GRADED positive rows, not 1244 and not the selected count.**
A hardcoded denominator is wrong for any `limit=N` run and silently wrong for our 4,182-row
selection. At the full split with every Case graded our denominator is 1,244 — identical to the
literal (F-4) — and on a subset it is the only correct choice.

AMENDED 2026-09-17 after review of PR #865. This decision previously said "the positive rows
actually **selected**", which the code never implemented: it counts positives among rows that
received a grade. The reviewer was right that the two must agree, and **graded** is the side to
keep, for two reasons:

1. **Consistency.** Every other denominator in this metric block — `accuracy`, `precision`,
   `recall`, `jaccard_mean`, `scored_cases` — is over graded Cases. Making laziness alone count
   ungraded rows would mean two metrics in one report answering different questions.
2. **It would credit a model for rows it never saw.** The reviewer's own example: two positive
   Cases, one falsely abstained and one whose request failed. Counting the failed Case gives
   50%, implying the model answered one correctly when it was never asked. That is the
   `failure_policy` INVARIANT in the other direction — an outage reading as diligence.

Pinned by `test_the_denominator_is_GRADED_positives_not_selected_positives`.

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

**D-8 · `interaction="single_shot"`. No `check_surface` at all.** One Candidate call per case;
the check is pure string work.

AMENDED 2026-09-18 (review of PR #984): this read `expected_check_cost="free"`, which described
a `check_surface` the board deliberately does not ship — so the spec contradicted the code and
would have sent a future author to "fix" the code back toward a trap. A declared surface is a
promise the SDK trusts BEFORE spend: declare one without registering the handler and a
corrective-loop run passes the pre-spend gate, burns paid candidate turns, then dies on a route
`runtime.install` never serves. Declare it only together with the handler — `grading.verdict`
is the parser it would use. The reasoning already lives correctly in `definition.py`'s
AIDEV-NOTE; only the spec was wrong.

## 4. Design

Board package mirrors `medxpert/` — the proven non-rubric shape (deterministic verdict, private
answer key), and the board that already made this exact migration (its reducer went 373 → 245
lines).

```
contracteval/
  pins.py            dataset + revision + prompt/protocol revisions + context guard
  prompts.py         the paper's system prompt and user template, verbatim
  grading.py         verdict(output, gold_spans) -> bool  ·  jaccard(gold, pred) -> float
  prepare.py         parquet → cases.json (public) + answers/<id>.json (private gold spans)
  case_evaluation.py bind/decode the per-Case envelope
  definition.py      revision hash, the url4 expression, BenchmarkDeclaration
  runtime.py         cases route, check endpoint, case-evaluation, aggregate
  aggregate.py       the board's grade_case + confusion-matrix scorer + failure wording
```

**The spine owns the marking room.** `spine/scored.py` runs the roll call, files rows by Case,
walks the failure ladder, assembles `CaseResult`s, and reduces the exam. This board supplies one
`ScoredPath` instance:

```python
_PATH = ScoredPath(
    reader=RowReader(benchmark_label="ContractEval", error_type=AggregateError,
                     decode_case_evaluation=_decode),
    grade_case=_grade_case,                       # the only per-board grading code
    failure_messages=_FAILURE_MESSAGES,           # board voice, not spine text
    method="containment",
    grading_failure_code="contracteval_grading_failed",
    grading_failure_message="the ContractEval checker could not grade this Case",
    missing_material_code="missing_answer_asset",  # NOT missing_rubric_asset — no rubric here
)
```

**The scorer is where this board is unusual, and the seam now fits it.** Every other board reduces
with `exam_scorer(mean)`. ContractEval cannot: its headline F1 comes from a dataset-level
confusion matrix, and a mean of case scores cannot reconstruct it — `0.0` is a false negative on
a positive row and a false positive on a negative one. `ScoredPath.aggregate()` accepts
`scorer: Callable[[Sequence[CaseResult]], CandidateScore]`, which is exactly general enough, so
the board passes its own `_confusion_matrix_score` and each Case carries `is_positive` /
`abstained` / `jaccard` in its grade metrics for the scorer to fold.

AIDEV-NOTE: that generality is recent. Before the spine overhaul the only reduction available
was a mean, and this board would have had to bypass the spine entirely.

The url4 expression is single-shot: one `candidate()`, then `check`, then `case-evaluation` via
the object-shaped `attempt_records_endpoint` (the array-shaped sibling is for rubric `iterate`
fan-outs and fails on this payload).

## 5. Error handling

- **The cases route preflights the whole bundle before serving any input** (review, PR #865).
  Handing out the booklet is the last moment before money moves; serving inputs and discovering
  a missing answer key at grading time means paying for inference that cannot be scored. The
  result is memoized, so the cost is one pass per process — and only a successful pass is
  cached, so a broken bundle re-fails on every call.
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
  values; laziness denominator = GRADED positives (D-3); Jaccard mean skips negatives.
- Unanswered case scores 0.0 and stays in the denominator (D-5); errored case scores `None`.
- `prepare.py`: parquet pin, public/private split, gold-span list validation, and the context
  guard both ways — passes on the pinned revision, raises on a synthetic over-budget row.
- Declaration guard tests updated for the new board (both are full-strength tables).

## 8. Out of scope

- FS-Research and the repeats/epochs protocol it needs — separate epic.
- Reconstructing the paper's 4,128-row subset (D-6).
- Any span-overlap or partial-credit grader — the protocol has none (F-1).
