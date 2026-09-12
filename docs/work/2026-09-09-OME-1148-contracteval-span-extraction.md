---
ticket: OME-1148
stack: screamingface-engine, screamingface
status: done
started: 2026-09-09
finished: 2026-09-09
---

# OME-1148 — Onboard ContractEval as a deterministic span-extraction benchmark

## Intent

Register the CUAD test split as an Engine-owned board reproducing the ContractEval protocol
(arXiv 2508.03080). The Candidate receives a full commercial contract plus one clause-category
question and must return the answering sentences VERBATIM, or the literal `"No related clause."`
Grading is entirely deterministic — span F1/F2, Jaccard, and the "laziness" false-abstain rate —
so this is the cheapest per-row board we carry: zero judge tokens.

It is also the first board with a span-overlap grader. The Engine has exactly three grading
methods today (`rubric` ×4 boards, `exact_match` ×2, `deterministic` ×1) and no span, F1, or
Jaccard code anywhere. MedXpertQA proved the non-rubric path — `spine.RowReader` without
`spine.CaseGrader` — and this board follows it.

Neutral board, as MedXpertQA was: the "laziness" metric is the same false-abstain lever as the
HealthBench refusal finding and may favour panels, but we report it because the paper does, not
to win.

## Prior art

- Paper: https://arxiv.org/abs/2508.03080 · https://aclanthology.org/2025.nllp-1.19/
- Reference harness: https://github.com/olivialiu121/ContractEval — **verified to exist, MIT**,
  carries `Evaluation.py` (F1/F2 · Jaccard · laziness). Mirror into `.refs/` per the
  protocol-alignment rule; do NOT reinvent the metric definitions.
- Dataset: https://huggingface.co/datasets/theatticusproject/cuad-qa (CUAD, CC BY 4.0)
- Prior costing/screening: `LiveTruth_leaderboard_work/docs/cost-workings-2026-07-21/e12-contracteval/`
  and `docs/new-benchmarks.md` in that repo.

## Open questions — ALL RESOLVED in the spec (2026-09-09)

Spec: `docs/spec/2026-09-09-OME-1148-contracteval-span-extraction.md`

1. **Dataset loading — SOLVED.** CUAD's HF `main` is script-loader only, but the auto-converted
   `refs/convert/parquet` branch exists at `d9c4ee0250ae2eb97bdb5b50773ab14ea62d0631`. Loaded
   successfully on `datasets 5.0.1`; 4,182 rows returned. We pin that revision.
2. **Row count — EXPLAINED.** HF test = 4,182 (102 contracts × 41 questions, verified). The
   paper's 4,128 is its own evaluated-output count, not a different key: the reference harness's
   hardcoded laziness denominator (1244) equals the FULL split's positive-row count exactly.
3. **Long context — measured.** min 645 · median 25,657 · max 300,768 chars. Explicit pinned
   truncation rule with a per-case `truncated` flag (D-7).
4. **Answer key — READ, and the July screening note was WRONG.** ContractEval is **not** a
   span-overlap benchmark. The per-row verdict is strict verbatim containment of *every* gold
   span (`all(substr in output)`), else abstain detection on negatives. F1/F2 are computed from a
   **dataset-level confusion matrix**, not per case. Jaccard is a secondary, positive-rows-only
   mean and is absent from the reference's headline results.

Net effect: **smaller** than the ticket assumed — no span-overlap grader is needed. The per-case
verdict is a boolean like MedXpertQA's; the novelty is confined to `aggregate.py`, which must
build a confusion matrix instead of averaging case scores.

## Planned changes

Plan: `docs/plan/2026-09-09-OME-1148-contracteval-span-extraction.md` — five tasks, of which
1-4 have landed. Files as built:

- `benchmarks/contracteval/` — `__init__ pins prompts grading prepare case_evaluation definition
  runtime aggregate` (no `answering.py`; see Deviations)
- `benchmarks/builtins.py` — registration
- `tests/unit/test_contracteval_{grading,prepare,case_evaluation,aggregate}.py` — 53 tests
- `tests/unit/test_benchmark_declaration.py` — one row added to the policy table
- `packages/screamingface/src/screamingface/_runtime/cli.py` — `_BENCHMARKS` + asset manifest
- `packages/screamingface/scripts/build_notebooks.py` + `examples/12_contracteval.ipynb`

## Test plan

53 tests across five modules, all written RED-first:

- `test_contracteval_grading.py` (20) — every branch of the containment verdict, abstention
  detection, and Jaccard, with three reference quirks pinned as protocol alignment.
- `test_contracteval_prepare.py` (14) — public/private split, polarity counts, the context
  guard both ways, and the module entry point.
- `test_contracteval_case_evaluation.py` (8) — the `attempt_1` envelope and the object-shaped
  route.
- `test_contracteval_aggregate.py` (13) — the confusion matrix against hand-computed F1/F2, the
  always-abstain zero guard, the laziness denominator, and the positive-rows-only Jaccard.
- `test_benchmark_declaration.py` — one row added to the policy table (owner-approved).

## Acceptance

- [x] `sf.evaluate(model, benchmark="contracteval")` runs end to end and reports F1/F2, Jaccard
      and laziness matching the paper's definitions.
- [x] The dataset is pinned reproducibly without the dead script loader; row count reconciled.
- [x] Over-long contracts have a documented, tested rule — a guard, not a truncation (D-7).

## First live run

`limit=8` against `openrouter/google/gemini-3.1-pro-preview` on the local stack. All 8 Cases
graded, coverage 1.0, no failures.

```
SCORE (F1): 0.8        accuracy 0.75   precision 0.6667   recall 1.0   f2 0.9091
TP 4 · FN 0 · TN 2 · FP 2
no_related_clause_rate 0.25   false_no_related_clause_rate 0.0   jaccard_mean 0.5834
```

Every published number reproduces by hand from the per-case list, which is the check that
matters most on a board whose score is a confusion matrix rather than a mean:

- `jaccard_mean` = mean of the four POSITIVE rows' Jaccards = 0.5834. Including the two abstained
  negatives would give 0.3889 — so the F-5 population rule is verified by the run itself, not
  only by its unit test.
- `false_no_related_clause_rate` is 0.0 because no positive row was abstained; the two errors
  were the opposite failure — answering on rows with no clause (FP), i.e. inventing a clause
  rather than being lazy.

Case 1 is the instructive one: score 1.0 with Jaccard 0.133. The gold span was the document-name
category (`"SUPPLY CONTRACT"`), which the long reply contains. Containment passes while token
overlap is low — exactly the reference's behaviour, and a good illustration of why Jaccard is a
secondary metric rather than the score.

## Outcome

- **Actual files:** as listed under Planned changes. Deviations: no `answering.py` (one function,
  folded into `grading.py`); the reference is cited by file+line rather than vendored, because
  `.refs/` is not a repo convention and the paper's matplotlib-importing script would fail this
  stack's gates.
- **Commits:**
  - `7c49cda8` docs(screamingface-engine): spec the ContractEval clause-extraction board
  - `fe972808` docs(screamingface-engine): plan the ContractEval board, and drop the truncation rule
  - `e73b4d07` feat(screamingface-engine): reproduce ContractEval's verdict and Jaccard
  - `640d03e1` feat(screamingface-engine): add the ContractEval board
  - `6293422d` feat(py-screamingface): register ContractEval in the SDK and add its notebook
- **Gates:** screamingface-engine ALL GREEN (2,656 tests, coverage 92%);
  screamingface ALL GREEN (coverage ≥95%, notebook + distribution checks included).
- **Deviations:**
  1. Two named deviations from the reference harness, each pinned by a test: the missing zero
     guard on `2PR/(P+R)`, and the hardcoded `1244` laziness denominator (spec D-3).
  2. One prior test modified — a single additive row in the declaration policy table. Owner
     approved; committed with `--skip-append-only`.
  3. `.refs/` vendoring dropped in favour of citation (above).
  4. Tasks 2 and 3 landed in one commit: the OME-1095 family guard requires a preparer's board
     to be registered in the same landing.

## Post-implementation audit (2026-09-09)

Asked to re-check the board for deviations, bugs and misnomers. A differential test of
`grading.py` against the reference's transcribed functions over **2,970 (output, gold) pairs on
400 real CUAD rows** found **zero** mismatches in verdict, abstention and Jaccard — the grading
core is bit-exact. It also confirmed the reference's own inconsistency (`startswith` vs `in`
disagree on both probes), and that we follow the `in` form, which is what `Evaluation.py` uses
for the published numbers.

Three real bugs in the code AROUND that core, all fixed:

1. **The envelope's own INVARIANT was unenforced.** `case_evaluation.py` promises "no inference —
   a malformed row fails here rather than becoming a silently missing score", but validated only
   `schema` and `case_id`. A record missing `correct` passed, and `bool(None)` is `False` in the
   reducer — which is NOT a missing score: it silently becomes a false negative on a positive row
   or a false positive on a negative one, depressing precision and recall with nothing reported.
   Every verdict field is now type- and range-checked on the way in.
2. **`is_positive` had two sources and no cross-check** — the baked key and the check record. A
   disagreement (stale bundle, wrong revision) filed the Case in the wrong matrix cell silently.
   Now fails as `polarity_mismatch`.
3. **The notebook sent `temperature`, which two of its three models reject.** OpenRouter answers
   `openai/gpt-5.5` with 404 for ANY temperature and `anthropic/claude-opus-4.8` with 400, while
   `gemini-3.1-pro-preview` and `qwen3.7-flash` accept it. The first pilot used gemini and so
   never hit it. The notebook now ships `{"max_tokens": 4096}` and names the failure modes.

One misnomer fixed: evidence `raw_output` carried the abstention flag rather than the producer's
output; it is now the containment verdict, matching IFEval's verifier evidence, with `abstained`
moved to metadata.

AIDEV-NOTE for future boards: `pins.TEMPERATURE` and `pins.MAX_TOKENS` are ADVISORY in every
board that has them — never applied, never hashed. Sampling reaches a model only from the SDK
caller's `sf.Model(params=...)`. Verified for both ContractEval and MedXpertQA.

## Still open at hand-off

- **Push and open the PR.** Not yet pushed.
- **The D9 landing-label split.** This ticket spans `apps/screamingface-engine` and
  `packages/screamingface`, and the card's D9 says ≥2 landings means an epic plus one sub-issue
  per landing. Filed as one ticket following the GDPval and MedXpertQA precedent — a deliberate
  choice, not an oversight, and the same one that left OME-1126 carrying a dangling
  `py-screamingface` label item.
- **The family guard does not prove a preparer runs.** It matches the command string against a
  regex; a preparer with no `main()` passes it and fails only at bake time with a message that
  hides the cause. Worth a shared test rather than the per-board one I added.
- **`error_context_head` is still dead for decode failures** in both `case_evaluation_endpoint`
  and `attempt_records_endpoint` (carried over from OME-1126) — `json_object` raises
  `ResolutionError`, which the handlers do not catch.
- **The name "span-extraction" is wrong** and survives in the Linear title and these four doc
  filenames. ContractEval has no span overlap — the verdict is all-or-nothing containment (F-1).
  The code never says it (`method: "containment"`, focus "Legal clause extraction"), and the spec
  title already reads "clause-extraction". Renaming the Linear issue is an owner action; the doc
  files should follow it in one move rather than drifting apart.
- **The system prompt is sent as user text, not a system message.** The reference uses
  `role: "system"` for its instructions; `candidate()` accepts a single `input` string and gives
  boards no system-role channel, so `render_case_input` concatenates. MedXpertQA hits the same
  wall and handles it WORSE — it defines `ANSWER_SYSTEM` and never uses it, silently dropping the
  official system prompt. Worth one shared ticket rather than two per-board workarounds.
- **No full-scale run.** 8 of 4,182 Cases have been graded. A full pass is ~$1.2-3.3k for a
  panel; the notebook says plainly that a small `limit` gives a real but very coarse F1.
