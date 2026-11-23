---
ticket: OME-1998
stack: screamingface-engine
status: done
started: 2026-11-21
finished: 2026-11-21
---

# healthbench-professional-paper-score — apply the paper's length adjustment and low judge effort to HealthBench Professional, and count failed Cases as 0

## Intent

HealthBench Professional's headline sits beside two published, length-adjusted numbers (0.437 and
0.647) but is computed differently in three ways, which an external researcher found and our own
Fidelity Record (`apps/screamingface-engine/docs/benchmarks-fidelity/healthbench-professional.md`,
deviations D1, D2 and D4) already rates `not-comparable`. This unit closes those three gaps as far
as code can: it applies the length-adjustment formula of
[the paper](https://arxiv.org/abs/2604.27470v1) and
[simple-evals](https://github.com/openai/simple-evals/blob/652c89d0ca9df547706735883097e9537d40dc47/healthbench_eval.py),
sends the judge low reasoning effort, and counts a failed Case as 0 over all selected Cases. The
three ride one new published revision (the owner approved the move on OME-1998). The result is
still not the paper's full protocol, so it is not called the paper's score anywhere: the paper
averages 8 samples per example, its judge is a dated snapshot we cannot reach, simple-evals never
scores a failed Case 0, and the published numbers came from an internal implementation.

## Planned changes

All in `apps/screamingface-engine`:

- `src/screamingface_engine_inspect/local_tasks/healthbench/scoring.py`: add
  `calculate_length_adjusted_score`, simple-evals' rule and names.
- `src/screamingface_engine_inspect/local_tasks/healthbench/healthbench.py`: `healthbench_rubric`
  takes the two length-adjustment settings (off by default, so healthbench worst-30 is unchanged);
  the Professional Task turns them on; `healthbench_clipped_mean` documents the failed Case at 0.
- `src/screamingface_engine_inspect/benchmarks.py`: the `healthbench-professional` row (judge
  `reasoning_effort=low`, the scorer's length-adjustment settings, `failure_policy="withhold"`,
  description, new `published_revision`), and the row field that lets a whole-run metric run under
  `withhold`.
- `src/screamingface_engine_inspect/single_shot.py`: the withhold guard and the whole-run tally.
- `src/screamingface_engine_inspect/local_tasks/healthbench/README.md`, `CHANGELOG.md`.
- Tests: `tests/unit/inspect/test_local_task_healthbench.py`,
  `test_local_task_healthbench_scoring.py`, `test_failure_policy_rows.py`,
  `test_failure_policy_revisions.py`, `test_benchmark_declaration.py`,
  `test_benchmark_fingerprints.py`, `test_published_revisions.py`, `test_whole_run_metric.py`.

## Test plan

Failing tests first:

- the length adjustment: rubric score 0.60 with a 4,000-character answer is 0.5412; the Fidelity
  Record's Case 1 values (empty answer 1.0588, 6,000 characters 0.8824); exactly 2,000 characters
  changes nothing;
- the scorer applies it only when both settings are given, and refuses one without the other;
- the Professional row: judge params carry `reasoning_effort=low`, policy `withhold`, the
  adjustment on; the worst-30 row and its numbers stay as they were;
- a failed Case enters Professional's clipped mean as 0 over all selected Cases, coverage still
  reads graded / selected, and a run with no gradeable Case publishes no score;
- the guard: `withhold` over a whole-run metric is still refused unless the row declares that the
  metric reads a failed Case as 0.

## Acceptance

- Each graded Professional Case files simple-evals' `overall_score_length_adjusted` in its
  evidence, and the headline is the clipped mean of those values over every selected Case, with
  a failed Case at 0.
- healthbench worst-30 grades exactly as before (its tests unchanged and green; only its
  fingerprint literal moves, because the Task package's source is hashed).
- The other whole-run rows stay `coverage_declare`.
- The published revision moves by the documented bump flow.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `src/screamingface_engine_inspect/scorer_metrics.py` (the
  bare 0.0 Score a failed Case hands a whole-run metric), `tests/unit/inspect/test_whole_run_metric.py`
  (one new test), `.claude/test-change-approvals/OME-1998.json`, this ledger and the mirror
  `docs/tasks/2026-11-21-OME-1998-healthbench-professional-paper-score.md`.
  `src/screamingface_engine/benchmarks/aggregation.py` (`policy_cases`) needed no change.
- **Commits:** two: `fix(screamingface-engine): score HealthBench Professional the paper's way`
  (`3149a02c0`), then a review-round commit that rewords every "the paper's score" claim.
- **Gates:** `uv run --isolated --extra inspect pytest` on 27 named test files (the two
  HealthBench files, the declaration, fingerprint, published-revision and failure-policy pins,
  the whole-run tally and guard, and the files that sweep every catalogue row): 1,865 passed,
  2 failed. Both failures are `enigmaeval`'s (`test_answer_formats_every_row.py`,
  `test_draft_feedback_on_page.py`), fail identically on `upstream/main` at `52b8e1ee3`, and are
  not touched here. `ruff check`, `ruff format --check` and `pyright` clean on the 13 touched
  Python files. `run_gates.py` was not run by hand (owner rule); the pre-push hook runs it.
- **New published revision:** `healthbench-professional` `d8fb037307f35415` → `35c7d07e9058f52d`.
  `healthbench-worst30` keeps `39cfd96b068f7230` (fingerprint `f12c3e30661ea9d3` →
  `75cdc1d5086ae220`, the hashed Task package source). After the review round Professional's
  fingerprint is `b46faf98e52d7a35`: only docstrings in the hashed package changed, every grade
  the same, so its published id held at `35c7d07e9058f52d` (the bump doc's rule for a code-only
  change).
- **Deviations:**
  - **What the Case row shows: decided by the owner on 2026-11-23, accepted as built.** The
    ticket says each Case's score becomes the adjusted one. Instead the Case Result keeps the
    rubric score, and the run averages the length-adjusted value from the Case's evidence
    (`overall_score_length_adjusted`, with `response_chars`). The reason: a length-adjusted value
    can pass 1 (a short answer that meets every rubric line is worth up to 1.0588; the Fidelity
    Record's Case 1 shows it), and the Engine's wire contract (`CaseGrade.score`, `le=1.0`) and
    the SDK both refuse a Case score above 1. The owner's decision: the Case row keeps the
    unadjusted rubric score, the adjusted value lives in the evidence, and the cap of 1 on a
    Case score stays. The description and the README say that the mean of the Case scores shown
    is therefore not the run score.
  - **How the withhold guard opened.** A new row field, `whole_run_failed_case_zero`, says the
    row's whole-run metric reads a failed Case as 0. The guard admits `withhold` beside a
    whole-run metric only with it, and refuses the flag without both. The guard cannot ask the
    metric itself: assembly never imports inspect. The guard moved into `_check_failure_policy`
    (the lint complexity limit on `single_shot_benchmark` was already reached).
  - **The length measured** is the Candidate's answer (`state.output.completion`), in characters:
    simple-evals passes `response_text`, the sampled response, to `len`.
  - **No `regradable_from`** on the row, against step 5 of the bump flow, which the bump command
    still prints for this row. The judge request changed, so a re-grade cannot replay an old
    entry's judge replies (OME-1979); declaring the pair would advertise a re-grade that fails.
  - **An abstained Case stays a flat 0**, as before (the lane's rule, OME-1289), with no length
    adjustment. simple-evals would grade its empty answer.
  - **Prior tests edited** (pinned tables and three HealthBench tests whose professional numbers
    changed), each listed with its reason in `.claude/test-change-approvals/OME-1998.json`. No
    assertion is weakened.
  - The PR is about 840 changed lines, above the 500-line guide. It is one grading change behind
    one revision bump, and more than half is tests and docstrings, so it was not split.

## Owner-verify note (pending owner steps)

- **One real judge call to confirm the provider accepts `reasoning_effort=low` on
  `openrouter/openai/gpt-5.4`.** No committed recording shows it (evidence under Review round 1).
  The smallest check, the SDK idiom of `packages/screamingface/examples/08_healthbench.ipynb`,
  against an Engine running this branch (a paid call: one Candidate answer and one judge call per
  rubric line of Case 1):

  ```python
  import screamingface as sf

  sf.connect()
  MODEL = sf.Model("openrouter/google/gemini-3-flash-preview")
  report = sf.evaluate(MODEL, benchmark="healthbench-professional", limit=1)
  report           # Case 1 shows a score: every judge call was accepted at effort low
  report.failures  # empty; a refused judge call shows here as a grading failure
  ```
- **Re-audit the Fidelity Record** with the fidelity agent
  (`apps/screamingface-engine/docs/benchmarks-fidelity/healthbench-professional.md`). Its verdict
  was not rewritten here; `just engine fidelity-check` lists it as stale (fingerprint
  `44ddda05be338699` → `35c7d07e9058f52d`), and healthbench-worst30's too.
- **Post to the team** that the published revision moved (step 4 of the bump flow).
- **Old leaderboard entries** under `d8fb037307f35415` leave the board. Each needs fresh judge
  calls to return (a paid run, the owner's).
- **No golden or snapshot was re-recorded.** healthbench-professional has none of its own. The
  recorded healthbench-worst30 e2e golden (`packages/screamingface/tests/e2e`) was not replayed
  by hand; CI's e2e lane is the check that it still replays.
- **Out of this unit, for a follow-up if wanted:** the SDK notebook
  `packages/screamingface/examples/08_healthbench.ipynb` still says professional's number is the
  one "to put next to published figures", and `apps/scoreboard/tests/fixtures/engine_catalog.json`
  is a recorded catalogue response that still carries the old description and revision.
- **Not this unit's:** `test_answer_formats_every_row.py` and `test_draft_feedback_on_page.py`
  fail for `enigmaeval` on `upstream/main` at `52b8e1ee3`.

## Review round 1 — 2026-11-21 (changes requested), addressed 2026-11-23

- **"The paper's score" overclaimed.** The row description, the Task README, the CHANGELOG line,
  the docstrings in `healthbench.py` and `scoring.py`, test names and comments, this ledger, the
  mirror, and the PR title and body now say what is computed: the paper's length-adjustment
  formula, low judge effort, failed Cases as 0, the mean clipped to 0..1. The description also
  says the Case row is unadjusted and that scores are not directly comparable to the published
  numbers, and names why (one answer per Case where the paper averages 8, another judge snapshot,
  failed Cases at 0). `test_the_description_says_what_is_computed_and_never_calls_it_the_papers_score`
  pins it, both clip bounds included.
- **The per-Case deviation needed a recorded owner decision.** The owner decided on 2026-11-23:
  accepted as built (first deviation above). The description, the README, the PR body and the
  approvals file record it.
- **`reasoning_effort=low` on `openrouter/openai/gpt-5.4`: the free evidence.** No model was called.
  - Other rows that pin it: gdpval-text, draco and draco-3pass, all on
    `openrouter/google/gemini-3.1-pro-preview`
    (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`, the
    `("reasoning_effort", "low")` lines). None is on gpt-5.4. The committed snapshots hold real
    judge replies for gemini-3.1-pro-preview (draco-3pass, gdpval-text) and for gpt-5.4 with no
    effort set (healthbench-worst30); none holds gpt-5.4 with effort low.
  - The gateway accepts `reasoning_effort` on OpenRouter for `low`, `medium` and `high` and
    passes it through under the same top-level name
    (`apps/aigateway/src/aigateway/plugins/openrouter_provider/parameters.py`,
    `OPENROUTER_REASONING_EFFORT_SCHEMA` and its `direct_rule`). The pinned litellm 1.102.1
    decides per model from its bundled model map: run offline, its
    `get_optional_params(model="openai/gpt-5.4", custom_llm_provider="openrouter",
    reasoning_effort="low", max_tokens=4096)` returns both parameters unchanged, and the map lists
    `openrouter/openai/gpt-5.4` with `supports_reasoning: true`. The gateway also forces
    `provider.require_parameters` on every OpenRouter call
    (`apps/aigateway/src/aigateway/plugins/openrouter_provider/routing_policy.py`), so an endpoint
    that does not support a sent parameter refuses the call instead of ignoring it.
  - [OpenRouter's public model listing](https://openrouter.ai/api/v1/models), read without a key
    on 2026-11-23: `openai/gpt-5.4` lists `reasoning_effort`, `reasoning` and `max_tokens` among
    its `supported_parameters` (and no `temperature`), and
    [its endpoints listing](https://openrouter.ai/api/v1/models/openai/gpt-5.4/endpoints) shows
    three OpenAI endpoints that list both `reasoning_effort` and `max_tokens`.
  - What this does not prove: that a real call is accepted and that the effort changes the
    judge's behaviour. That is the one real call in the owner-verify note.
- **Tests after the round:** the same 27 named files, counts in the PR body.
