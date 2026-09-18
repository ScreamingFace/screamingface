---
ticket: OME-1148
stack: screamingface-engine, screamingface
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1148 — ContractEval as a judge-free clause-containment board (rebuild on the new spine)

## Intent

Register the CUAD test split (4,182 rows over 102 commercial contracts × 41 clause categories)
as an Engine-owned board reproducing the ContractEval protocol (arXiv 2508.03080). The Candidate
receives a full contract plus one clause-category question and must quote the answering
sentences VERBATIM, or the literal `"No related clause."` Grading is deterministic string
containment — zero judge tokens.

This is a **rebuild**, not a fresh onboarding. A complete implementation was written on
2026-09-09 (8 commits, both stacks green, live-verified), but PR #865 was closed unmerged and
`main` has since moved 191 commits under an onboarding-infra overhaul. The work is preserved at
tag `OME-1148-v1-pre-overhaul` (`b39c5da2`) and on `origin/OME-1148-contracteval`.

## Why the rebuild is not a rewrite

The overhaul replaced `spine.CaseGrader` with a `grade_case` seam (`spine/scored.py`). The spine
now owns the marking room — roll call, row filing, the failure ladder, result assembly, and the
exam reduction. A board contributes `grade_case`, its failure wording, and its scorer.

Two consequences, both verified against `main` before starting:

1. **The expensive part survives.** `grading.py` is pure protocol: the containment verdict,
   abstention detection, and Jaccard, each mirroring the reference by file and line. It was
   differential-tested against the reference's transcribed functions over 2,970 (output, gold)
   pairs on 400 real CUAD rows with **zero** mismatches. None of that depends on the spine.
2. **My prior objection to the spine is resolved.** I recorded (2026-09-13, reviewing the
   inspect-import architecture) that the spine had no aggregation seam, so this board's
   confusion-matrix score had nowhere to go. `ScoredPath.aggregate()` now takes
   `scorer: Callable[[Sequence[CaseResult]], CandidateScore]` — fully general;
   `exam_scorer(mean)` is only the rubric convenience. The existing
   `_confusion_matrix_score` binds directly.

## Established facts carried forward (unchanged by the overhaul)

Spec: `docs/spec/2026-09-17-OME-1148-contracteval-containment.md` (F-1…F-10, D-1…D-8 intact).
The protocol, the dataset pin, the measurements and the deviations are properties of
ContractEval and CUAD, not of our infrastructure. Re-verified on this branch:

- **Not importable.** ContractEval is absent from inspect_evals (171 evals). `ContractBench`
  there is software/API contracts — presigned URLs, OAuth tokens, HMAC webhooks — a name
  collision, nothing more. So this board stays hand-authored; the import path does not apply.

## Planned changes

Modelled on `medxpert/` — the closest analogue (deterministic, non-rubric, private answer key),
whose reducer went 373 → 245 lines through this same migration.

- `benchmarks/contracteval/` — `pins.py` `prompts.py` `grading.py` `prepare.py`
  `case_evaluation.py` `definition.py` `runtime.py` `aggregate.py` `__init__.py`
- `benchmarks/builtins.py` — registration
- `tests/unit/test_contracteval_*.py`
- `packages/screamingface/src/screamingface/_runtime/cli.py` — `_BENCHMARKS` + asset manifest
- `packages/screamingface/scripts/build_notebooks.py` + the generated notebook

## Test plan

Port the 68 tests from the tag first — they are the regression net for the migration, and any
that fail identify exactly where the new seam differs from the old assumption. Then add tests
for whatever the new `ScoredPath` wiring introduces.

## Acceptance

- `sf.evaluate(model, benchmark="contracteval")` runs end to end, reporting F1/F2, Jaccard and
  laziness matching the paper's definitions.
- The dataset is pinned reproducibly without the dead script loader.
- Both stacks' gates green; a live run grades real cases.

## How much the overhaul actually cost

Measured before porting, by diffing MedXpertQA across the 191 commits:

```
medxpert/aggregate.py    373 → 245   (119 insertions, 254 deletions)
every other module       UNCHANGED
its unit tests           UNCHANGED
```

One file, and its tests did not move — so the rewrite was internal and the public contract
held. That measurement is what turned this from "rebuild a board" into "port seven files and
migrate one", and it predicted the outcome exactly: all 68 tests passed **unmodified**.

## Outcome

- **Actual files:** `contracteval/` — `pins prompts grading prepare case_evaluation definition
  runtime` ported byte-identical; `aggregate.py` rewritten onto `ScoredPath` (414 → ~250 lines).
  `builtins.py`, `cli.py`, `build_notebooks.py`, `examples/12_contracteval.ipynb`, and one
  additive row in `test_benchmark_declaration.py`.
- **Commits:** `a0a56a26` (docs restart) + the implementation commit below.
- **Gates:** screamingface-engine ALL GREEN; screamingface ALL GREEN.
- **Deviations:** the five named in the spec are unchanged. One process deviation: the
  declaration guard row was re-applied under the owner's prior ruling on the identical edit
  (2026-09-09) rather than re-asking, and committed with `--skip-append-only`.

## Verification — three independent checks, because "green" is not "behaviour-preserving"

1. **Protocol fidelity.** The differential test against the reference's transcribed functions,
   re-run after porting: **2,742 (output, gold) pairs over 400 real CUAD rows, zero mismatches**
   in verdict, abstention and Jaccard.
2. **Asset identity.** Rebake returned `4,182 / 1,244 / 2,938` at dataset revision
   `d9c4ee02…`. The 1,244 is the constant the reference hardcodes as its laziness denominator,
   so the pin still addresses the exam the paper scored.
3. **Scoring behaviour.** The live `limit=8` pilot reproduced the pre-overhaul run
   **cell-for-cell** — TP 4 · FN 0 · TN 2 · FP 2, F1 0.80, precision 0.6667, recall 1.0,
   F2 0.9091, accuracy 0.75. Only `jaccard_mean` moved (0.5834 → 0.578), and only because one
   model reply came back worded differently; no confusion-matrix cell changed.

## What the new spine changed for this board

`ScoredPath` absorbed the failure ladder, result assembly, roll call and row filing. Two of the
bugs found the hard way in the first implementation moved rather than vanished, and both landed
somewhere better:

- the **polarity cross-check** is now a `CaseGradeOutcome.failure_code` returned by
  `grade_case`, instead of a hand-rolled ladder rung competing with the spine's own rungs;
- the **verdict-field validation** stays in the envelope decoder, which is still the only place
  that can catch a record missing `correct` before `bool(None)` silently files it as a false
  negative.

The F1/F2 zero guard and the selected-positives laziness denominator are unchanged.

AIDEV-NOTE for the next board author: `ScoredPath.aggregate()` takes
`scorer: Callable[[Sequence[CaseResult]], CandidateScore]` — fully general. `exam_scorer(mean)`
is the rubric convenience, not the contract. A board whose headline is not a mean of case
scores (this one's is a confusion matrix) passes its own builder and carries whatever each Case
needs in that Case's grade metrics.

## Review log — PR #984

**Round 1** (two findings, both real, both fixed):

- `preflight()` was defined, exported, and called from nowhere: a missing answer key surfaced
  only at grading time, after inference was paid for. The cases route now preflights before
  serving, memoized (1.63s once per process for 4,182 records, 0.003ms after).
- Spec and code disagreed on the laziness denominator — "selected" vs "graded" positives. The
  reviewer left the choice open; graded wins, because dividing by selected credits a model for
  rows it never saw (D-3 carries the reasoning).

**Round 2** (the harder round — the findings were about the *evidence*, not the code):

- **Fidelity was asserted and never pinned, and every provenance pointer was dead.** The spec
  promised a `.refs/` mirror that was never committed; `grading.py` pointed at a spec filename
  that exists on no branch; `prompts.py` and spec F-8 gave different line ranges and neither
  matched the source (verified: system prompt 75-79, template 19-27); and no test mentioned
  `SYSTEM_PROMPT`. A transcription typo was undetectable with every gate green.

  Fixed by making the claim testable rather than restating it: `tests/unit/_contracteval_reference.py`
  (the four reference functions, verbatim, DO-NOT-EDIT), `tests/unit/data/contracteval_gold_spans.json`
  (120 real CUAD rows, gold spans only — the parity test compares GRADERS, which never need the
  contracts — with provenance and CC BY 4.0 attribution), `test_contracteval_parity.py`, and
  `test_contracteval_prompts.py`.

- **All three published metrics were pinned at fixtures where the right formula and the wrong
  ones agree.** The confusion-matrix fixture was 2 TP / 1 FN / 1 TN / 1 FP, where precision ==
  recall == 2/3 — so F1, F2, F2-with-beta-inverted, the arithmetic mean of P and R, and P and R
  themselves all equal 0.6667. Five formulas, one number. Both laziness fixtures and the
  evidence test were degenerate the same way.

  AIDEV-NOTE — the lesson worth keeping: those tests cited *hand-computed* values, which is
  what made them look rigorous. Hand-computing does not prove a fixture discriminates. The
  fixtures are now asymmetric, and **seven mutants were introduced to prove it**: F2 with beta
  inverted, laziness over total abstentions (caught by two tests), precision/recall swapped,
  `raw_output` as the negated abstention flag, abstention via `startswith`, Jaccard via
  `.split()`, and the em dash normalised to a hyphen. Every one fails; the suite is green
  restored. My first replacement assertion was itself wrong — I wrote accuracy 0.75 where
  (3+2)/8 = 0.625 — which is the same lesson arriving twice.

**Paper trail and mechanical items:** spec D-8 no longer claims `expected_check_cost="free"` for
a board that ships no check surface; the `.refs/` promise is retracted with its reason; both line
citations corrected; `pins.py`'s header no longer claims every value is hashed (`MAX_TOKENS`,
`TEMPERATURE`, `MAX_CONTEXT_TOKENS` are not); `TEMPERATURE` is a float, since its only purpose is
to be copied into `params=`; `prepare.py` validates `source_id`/`title` instead of trusting them
(verified against all 4,182 rows); the dead `attempt.get("metadata")` read is gone with a note
naming the real seam; the context guard is pinned both ways; the notebook now states the ~23M
input tokens per member a full pass costs; and the declaration guard row records its approval
where the next reader of that file will see it.

**Round 3** — the seven "review recommended" items. Five were this board's gaps and are
closed; two are cross-board and are not this ticket's to fix:

- **#9 was worse than the review estimated.** It guessed "100+ MB" for the memoized booklet.
  Measured: `cases.json` is 201.5 MB and the serialized payload is **403 MB resident** (Python
  strings cost two bytes per character here), retained for the process lifetime in a mode where
  one process serves many runs. So it is fixed rather than documented: the memo holds the
  PREFLIGHT VERDICT, not the bytes — matching `medxpert/runtime.py` — and the expensive check is
  still paid once. That also closed the spec §5 promise the review found untested ("only a
  successful pass is cached"), which both earlier preflight tests missed by building a fresh
  closure and calling it once.
- **#5 is now the strongest test in the unit suite.** `test_contracteval_resolution.py` drives
  cases → candidate → check → case-evaluation → aggregate in-process against a mocked gateway,
  so it costs nothing. Mutation-verified against BOTH OME-1126 failure modes: rebinding
  `$item.input` to a name that does not exist (the empty-prompt-to-a-paid-model bug) and the
  array-shaped case-evaluation payload. Parsing alone could not catch either, because url4's
  resolver answers an unknown `$name` with empty text rather than an error.
- **#4** `test_contracteval_check_route.py` — the one production site where `grading` meets a
  real candidate payload. Pins the D-5 empty-reply case (`correct=False` AND
  `abstained=False`, so an empty reply cannot earn a true negative) and that `_check`'s output
  satisfies `bind_case_evaluation`'s validator, which previously failed only at runtime.
- **#6** the system-prompt role is now spec **D-9** plus a caveat in the board `description`,
  where a leaderboard reader sees it. Fixing it properly needs a system-role channel at the
  candidate boundary — shared with MedXpertQA, so its own ticket.
- **#7** `pins.EXPECTED_CASES` is enforced in `load_rows`, and `definition.CASE_COUNT` now
  references it rather than carrying a second literal.
- **#8** `test_contracteval_definition.py` (11 tests, and the first caller of
  `compute_revision`'s injectable kwargs), plus the e2e `BOARDS` tuple and bundle map, plus the
  `test_runtime_cli` fingerprint parametrize.

**NOT done — needs its own ticket.** #3: `_benchmark_fingerprint` returns `<name>:<DATASET_REVISION>`
for every board, so a prompt edit re-addresses every route while `screamingface prepare` reports
"already prepared" and serves the old booklet under the new revision. `PREPARER_REVISION` is
invisible to it. The one-line fix invalidates every existing manifest and forces a re-prepare
across all seven boards, which is a behaviour change for boards this ticket does not own.
Also not done: `runtime.py`'s `json.loads` sits outside the `_unavailable`-converting path, so a
malformed `cases.json` surfaces as a bare `JSONDecodeError` — byte-identical in medxpert, and
the reviewer scoped it out of this PR themselves.

Test count: 71 → 84 → 87 → **113**.

## Still open at hand-off

- **PR #984 is open and under review.** Two rounds of findings addressed — see the review log
  below.
- **The Linear title still says "span-extraction".** The protocol reading disproved that name —
  the verdict is all-or-nothing containment and the code says `method="containment"`. The doc
  files are already renamed; the issue rename is an owner action.
- **The system prompt is sent as user text.** `candidate()` takes a single `input` string and
  offers boards no system-role channel, so `render_case_input` concatenates. MedXpertQA has the
  same constraint and handles it worse — `ANSWER_SYSTEM` is defined and never used, silently
  dropping the official system prompt on a merged board. Worth one shared ticket.
- **No full-scale run.** 8 of 4,182 Cases graded.
- **Not importable.** Re-verified on this branch: ContractEval is absent from inspect_evals;
  `ContractBench` there is software/API contracts. If it is ever contributed upstream, this
  board becomes two data rows in `screamingface_engine_inspect/boards.py`.
