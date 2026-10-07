# One Benchmark, several Named Scores (PRs 2–5 of the OME-1268 stack) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an inspect Task with several scorers, or one scorer returning a dict of numbers,
land as one Benchmark whose Case Grades and Candidate Result carry every score by name in a typed
`scores` field, with one declared Headline Score in `score`; then import MATH (two of three
scorers, the third dropped by name) and SQuAD (two scorers, list-of-answers target).

**Architecture:** One optional wire field on both sides of the `screamingface.candidate-result.v1`
contract, added absent-unless-set like `inverted_grade`. The Engine's inspect adapter grades a
Case once per declared scorer and writes the named values; the reducer averages each column; the
row declares the extra scorers, the headline key and any dropped scorer, and all three pin into
the Benchmark Revision. The importer learns to keep every conservable scorer, to refuse a
formula headline by name (the tripwire), and to accept a list-of-strings target. The SDK
decodes the key, writes it to report.json, exposes `result.scores`, and shows a `scores` block
on the report card.

**Tech Stack:** Python 3.12, uv, pytest, pydantic v2 (Engine wire models), `inspect-ai`
0.3.263, `inspect-evals` 0.20.0.

**Spec:** `docs/spec/2026-10-05-OME-1268-multi-score-benchmarks.md`. Decisions 1–8 are on
OME-1268 (owner, 2026-10-05). This plan amends the spec where the recon below is more precise
(§2.2's row fields, §2.7's report.json key, §8.5's byte-identity claim); the spec was updated in
the same PR to match.

## Global Constraints

- One worktree per PR, off `upstream/main`:
  `git worktree add .claude/worktrees/<slug> -b <slug> upstream/main`; rename to
  `OME-1268-<slug>` at PR-open. Every PR carries `Refs: OME-1268` and a title ending in
  `(OME-1268, PR k of 5)`; the docs PR (#1235) is PR 1 of 5.
- Paths are relative to `apps/screamingface-engine/` (**E**) or `packages/screamingface/`
  (**S**) as marked; `docs/` paths are repo-relative.
- Engine: `uv sync --extra inspect --inexact` once per worktree, then `uv run pytest <path> -q`.
  SDK: `uv sync --extra notebook --inexact`.
- Gates before each PR, from the repo root: `uv run .claude/scripts/run_gates.py
  screamingface-engine` or `... screamingface` (append-only test check, ruff, format, pyright,
  layering, pytest with coverage).
- **Deploy order: PR 2's SDK releases before PR 3's Engine deploys.** The SDK decoder refuses
  unknown keys (`_keys`, S `src/screamingface/_evaluation/results.py:492`), so an Engine emitting
  `scores` to an older SDK fails every multi-score run.
- `tests/unit/inspect/test_published_revisions.py` passes unchanged: no published Benchmark
  Revision moves. Every single-scorer run result is byte-identical (the field is absent).
- Glossary words only (`CONTEXT.md`): Case, Case Grade, Candidate Result, Check, Evidence, Case
  Preparation, Grading Material, Named Deviation, Headline Score, Named Score. Never "board",
  "sub-score", "metric" for a Named Score.
- Plain `test_` functions; type every argument, return and non-obvious local; one-sentence
  intuition docstring per function; `WHY:` / `INVARIANT:` anchors, no restating comments.
- Tests are append-only. Two prior-test edits are known in advance and need the owner's
  `--skip-append-only`, asked for by name in the PR body (Task 2.5 and Task 3.1).
- Stage explicit paths, never `git add -A`. Conventional commits, no `Co-Authored-By`.
- Nothing in any test touches the network or a model. Paid runs are the owner's.

## Decisions taken in this plan (owner can flip any before coding starts)

| # | Decision | Why | Flip means |
|---|---|---|---|
| D1 | **`scorer` stays the Headline Score's scorer; the row adds `extra_scorers: tuple[str, ...]`** (dotted references like `scorer`, in upstream order) for the other Named Scores | a single-scorer row renders byte-identical; the headline cannot disagree with the scorer that produces it, so the spec's "headline not in scorers" failure mode cannot arise | a `scorers` list plus a `headline` name, and an assembly check that they agree |
| D2 | **Named Score keys are inspect registry names** (`registry_info(scorer).name`: `f1`, `exact`, `expression_exact_match`), declared on the row as `named_scores: tuple[str, ...]`, headline first | the key must be stable across Engine versions and readable in a paper's terms; the importer fills it for multi-scorer rows, a hand-written row fills it for a dict-valued scorer | derive at run time from the resolved scorers (then a dict-valued scorer has no declared keys to validate against) |
| D3 | **`dropped_scorers: tuple[str, ...]` is the Named Deviation field** for a scorer left out by name; it pins into the Revision with `extra_scorers` and `named_scores` | the drop must be visible on the row and change identity | a prose-only note in the description (invisible to the Revision) |
| D4 | **The wire model validates values; the aggregation validates keys.** `CaseGrade.scores` values are finite or `None` and keys non-empty strings; `_scored_result` asserts the key set equals `named_scores` and `scores[named_scores[0]] == score` | the wire model cannot see the row; the aggregation can, and it is where the dict is built | a declared-keys field on the wire model (a contract change for every Benchmark) |
| D5 | **The reducer averages every column over the Cases with a numeric `grade.score`**, the same Case set as the headline, so all columns share Coverage's denominator | a half-graded Case is refused by D6, so the sets are equal by construction | per-column denominators (then `scores` and `coverage` can disagree) |
| D6 | **One scorer failing fails the Case** as `invalid_score_value` naming the scorer; no partial `scores` | the column means must share a denominator (D5) | partial grades plus a per-column coverage |
| D7 | **report.json emits `scores` on every Case Grade and Candidate Result, `{}` when absent** (the report's stable-key convention, `answer_seed`); the wire omits it unless set | a reader sees an empty dict instead of guessing; same choice as `inverted_grade: false` in OME-1400's PR 2 | emit only when non-empty (report.json then differs in shape between Benchmarks) |
| D8 | **The tripwire lives in the importer's scorer-line renderer** (`_scorer_lines`, E `importer.py:1220`) next to the custom-metric TODO it already writes, and reads the headline scorer's declared metrics by registry name (`_custom_metrics`, E `importer.py:270`) | the facts are already read there; one place | a run-time check (too late: the Benchmark would already be published) |
| D9 | **SQuAD's list target is frozen as a JSON list in the Grading Material** (`{"target": ["1889", "1887–1889"]}`); the adapter already passes `material["target"]` to inspect's `Target`, which accepts a list | the scorer reads exactly the value upstream reads; no grading code changes | join into one string (changes `f1`'s best-match semantics) |
| D10 | **MATH's temperature is written as a `dropped_config` Named Deviation in the row's description only**, not a pinned field | the importer never reads `task.config` today (recon); conserving it is its own unit, and pinning a value we do not apply would lie | a pinned field now, applied by nobody |

## Review Focus

1. **A multi-score Case Grade on the wire must round-trip the SDK unchanged.** `scores` is
   emitted by the Engine, decoded by `_case_grade` and `_candidate_payload`, written by
   `CandidateResult.to_dict`, and rebuilt by `examples/helpers.py:load_candidate_result`. Four
   sites, one shape. Pinned in Task 2.2 (`test_scores_round_trip_through_report_json`) and the
   Engine twin in Task 3.6.
2. **The headline column must equal `score`.** If the adapter computed `score` from one call and
   `scores[headline]` from another, a non-deterministic scorer could make them differ. One call
   per scorer; `score` is read from the dict. Pinned in Task 3.2
   (`test_headline_score_is_the_named_headline_column`).
3. **A dict-valued Score with an undeclared key must fail the Case, not drop the key.** Pinned in
   Task 3.3 (`test_an_undeclared_dict_key_fails_the_case_by_name`).
4. **The inverted flip and the word map apply to the headline scorer only.** Pinned in Task 3.2
   (`test_inverted_grade_flips_the_headline_only`).
5. **Single-scorer rows render and grade byte-identically.** The `render_generated_rows` tests
   in `test_inspect_importer.py` and `test_published_revisions.py` pass unchanged; a new test
   asserts a single-scorer Case Grade has no `scores` key on the wire (Task 3.1).
6. **The tripwire refuses `simpleqa` by name and accepts cyberseceval_4's shape.** Pinned in
   Task 4.3 (`test_a_formula_headline_metric_is_refused_naming_it`,
   `test_a_grouped_metric_on_a_non_headline_scorer_is_a_named_deviation`).
7. **The Revision moves when and only when a multi-score field changes.** Pinned in Task 3.5
   (`test_extra_scorers_pin_into_the_revision`, `test_a_single_scorer_row_has_no_score_pins`).

---

## PR 2 — SDK: decode, report, show (branch `OME-1268-sdk-named-scores`)

Lands in S. Releases before PR 3 deploys.

> **As built (2026-10-06).** Two places differ from the tasks below. (1) `CaseGrade.to_dict`
> writes `scores` only when set: the Case Grade dict is pinned one-to-one to the Engine's wire
> by the exact-contract round-trip tests (`test_case_outcome_decoding`, `test_case_results`,
> `test_candidate_result_coverage`), so the stable `{}` key lives on the Candidate Result only
> (D7 narrowed). (2) Task 2.5 was not needed: no prior test asserts a full Candidate dict, so
> the only prior-test change is the public-surface snapshot (Task 2.3). All new tests live in
> one file, `tests/test_named_scores.py`, instead of appended to four.

### Task 2.0: Ledger

**Files:**
- Create: `docs/work/2026-10-06-ome-1268-sdk-named-scores.md` from `docs/work/TEMPLATE.md`,
  `ticket: OME-1268`, status `in_progress`.

- [ ] **Step 1: Write the ledger** (Intent = this PR's row in the spec's §7; Planned changes =
  Tasks 1.1–1.5's files; Test plan = the test names below; Acceptance = spec §8 items 3, 5, 6
  for the SDK side).
- [ ] **Step 2: Commit** `docs(screamingface): ledger for SDK named scores`.

### Task 2.1: `CaseGrade.scores` and `CandidateResult.scores` dataclass fields

**Files:**
- Modify: `src/screamingface/case_result.py` (`CaseGrade`, :216; `__init__` :225; `to_dict`
  :252)
- Modify: `src/screamingface/report.py` (`CandidateResult` :185; `__init__` :223; `to_dict`
  :334)
- Test: `tests/test_case_results.py`, `tests/test_report.py` (append)

- [ ] **Step 1 (RED):** `test_case_grade_carries_named_scores_as_a_frozen_mapping` (a
  `CaseGrade(scores={"f1": 0.667, "exact": 0.0})` exposes `.scores` as a read-only mapping;
  default is `{}`); `test_case_grade_rejects_a_non_finite_named_score` (NaN raises `ValueError`
  naming the key); `test_candidate_result_carries_named_scores` (same shape on the result;
  an unscored result with non-empty `scores` raises, mirroring the `metrics` rule at :256).
- [ ] **Step 2 (GREEN):** add `scores: Mapping[str, float | None]` keyword (default `{}`) to
  both constructors, frozen via `freeze_mapping`, validated with `_optional_number` per value;
  `to_dict` emits `"scores"` always (D7). `WHY:` anchor on the stable-key choice.
- [ ] **Step 3:** run `uv run pytest tests/test_case_results.py tests/test_report.py -q`.
- [ ] **Step 4: Commit** `feat(screamingface): carry named scores on Case Grade and Candidate
  Result`.

### Task 2.2: Decode `scores` from the wire and rebuild it from report.json

**Files:**
- Modify: `src/screamingface/_evaluation/results.py` (`_case_grade` :380, `_candidate_payload`
  :209, `_candidate_components` :257, `_candidate_result` :122)
- Modify: `examples/helpers.py` (`load_candidate_result` :34)
- Modify: `src/screamingface/_report_primitives.py` or the SDK's catalogue vocabulary module
  (add `SCORES_KEY = "scores"` beside `INVERTED_GRADE_KEY`)
- Test: `tests/test_case_result_contract_boundaries.py`, `tests/test_report.py` (append)

- [ ] **Step 1 (RED):** `test_case_grade_decodes_an_optional_scores_key` (a wire Case Grade
  with `scores` decodes; without it `scores == {}`); `test_candidate_payload_decodes_an_optional_
  scores_key`; `test_a_non_mapping_scores_value_is_refused` (a list raises the same
  `ValueError` family as a bad `metrics`); `test_scores_round_trip_through_report_json`
  (Engine-shaped dict → `CandidateResult` → `to_dict` → `load_candidate_result` → equal
  `scores` on Case Grade and result).
- [ ] **Step 2 (GREEN):** add `optional={SCORES_KEY}` to `_case_grade` and `_candidate_payload`
  (the `operations` / `INVERTED_GRADE_KEY` pattern), thread the value through
  `_candidate_components` and `_candidate_result`, and read it back in `load_candidate_result`.
- [ ] **Step 3:** run the two test files.
- [ ] **Step 4: Commit** `feat(screamingface): decode named scores from the run result`.

### Task 2.3: `result.scores` is public

**Files:**
- Modify: `src/screamingface/report.py` (a `scores` property beside `metrics` :327)
- Modify: `tests/public_surface_snapshot.json` (regenerated with
  `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py`)

- [ ] **Step 1 (RED):** `test_public_surface.py` fails on the new constructor keyword and
  property.
- [ ] **Step 2 (GREEN):** regenerate the snapshot. **This is prior-test change #1: name it in
  the PR body and ask the owner for `--skip-append-only` (or an approval manifest under
  `.claude/test-change-approvals/`).**
- [ ] **Step 3: Commit** `feat(screamingface): expose result.scores`.

### Task 2.4: The `scores` block on the report card

**Files:**
- Modify: `src/screamingface/_ui/report_view.py` (`_card_html` :295 adds `_scores_html` after
  `_coverage_notice_html`; new `_scores_html` and `_score_row` beside `_axes_html` :411 and
  `_axis_row` :423, reusing `.sf-axes` / `.sf-axis` CSS :166–173)
- Test: `tests/test_report_panel.py` (append)

- [ ] **Step 1 (RED):** `test_scores_block_renders_one_row_per_named_score_with_the_headline_
  tagged` (two named scores → a `scores` label, two `sf-axis` rows, `_score_text` formatting,
  the word `headline` on the headline row only); `test_scores_block_is_absent_for_a_single_
  score_candidate` (empty or one-entry `scores` → no block, HTML byte-identical to today).
- [ ] **Step 2 (GREEN):** implement; the headline row is the one whose value equals
  `candidate.score` and whose key is first in insertion order (the Engine writes it first, D2).
- [ ] **Step 3:** run `tests/test_report_panel.py`, then a deterministic notebook check per
  the stack card.
- [ ] **Step 4: Commit** `feat(screamingface): show named scores on the report card`.

### Task 2.5: Report JSON stable key and prior-test edits

**Files:**
- Test: `tests/test_report.py`, `tests/test_answer_seed_report.py`,
  `tests/test_inverted_grade_report.py` (any full-dict equality on a candidate or Case Grade
  dict now needs `"scores": {}`)

- [ ] **Step 1:** run the SDK suite; list every failing prior test and the one key it needs.
- [ ] **Step 2:** edit those assertions only. **This is prior-test change #2: name each file in
  the PR body under the same `--skip-append-only` ask.**
- [ ] **Step 3:** `uv run .claude/scripts/run_gates.py screamingface` green (with the owner's
  flag on the append-only lane).
- [ ] **Step 4: Commit** `test(screamingface): report.json carries scores as a stable key`.

### Task 2.6: PR-open

- [ ] Rename branch, open the PR `feat(screamingface): decode and show named scores (OME-1268, PR 2 of 5)`
  with the Review order and the two named prior-test edits; mark the deploy note **release
  this SDK before any Engine from PR 3**.

---

## PR 3 — Engine: the spine (branch `OME-1268-engine-named-scores`)

Lands in E. Deploys after PR 2's SDK release.

> **As built (2026-10-06).** Five places differ from the tasks below; the ledger records why.
> (1) The branch is stacked on PR 2's branch so the SDK key twin test can pass; retarget to
> `main` after #1248 merges. (2) A dict-valued scorer writes one Check (id `"1"`) with the
> headline key's grade, not a Check per key. (3) `extra_scorers` are default-constructed (no
> kwargs twin yet). (4) The word map applies to the headline scorer only; other scorers speak
> inspect's letters. (5) All new tests live in four new files instead of being appended to
> three existing ones.

### Task 3.0: Ledger

- [ ] Create `docs/work/2026-10-07-ome-1268-engine-named-scores.md`; commit.

### Task 3.1: `scores` on the wire models, absent unless set

**Files:**
- Modify: `src/screamingface_engine/benchmarks/contract.py` (`CaseGrade` :201,
  `CandidateResult` :413, `_candidate_outcome` :496; `_StrictWireModel._validate_open_json_
  mapping` :143 only checks `metadata` / `metrics`, so `scores` gets its own validator)
- Modify: `src/screamingface_engine/benchmarks/definition.py` (`SCORES_KEY = "scores"` beside
  `INVERTED_GRADE_KEY` :71)
- Test: `tests/unit/test_candidate_result_contract.py`, `tests/unit/test_catalogue_vocabulary_
  conformance.py` (append)

- [ ] **Step 1 (RED):** `test_case_grade_scores_is_absent_from_the_payload_when_empty`
  (`CaseGrade(...).model_dump()` has no `scores` key; `as_payload` byte-identical to a
  pre-change fixture); `test_case_grade_scores_values_must_be_finite_or_none`;
  `test_case_grade_scores_keys_must_be_non_empty_strings`;
  `test_candidate_result_scores_is_absent_when_empty`;
  `test_an_unscored_candidate_result_has_no_scores` (mirrors the `metrics == {}` rule);
  `test_scores_key_matches_the_sdk` (the AST conformance pattern at :78, pinning
  `SCORES_KEY` against the SDK module from PR 2).
- [ ] **Step 2 (GREEN):** `scores: dict[str, float | None] = Field(default_factory=dict,
  exclude_if=lambda value: not value)` on both models, a `field_validator` reusing
  `_finite_score` per value; the unscored rule in `_candidate_outcome`. `INVARIANT:` anchor:
  absent unless set, so single-scorer payloads never change.
- [ ] **Step 3:** `uv run pytest tests/unit/test_candidate_result_contract.py -q`.
- [ ] **Step 4: Commit** `feat(screamingface-engine): carry named scores on the wire, absent
  unless set`.

### Task 3.2: The adapter grades once per scorer

**Files:**
- Modify: `src/screamingface_engine_inspect/scorer_adapter.py` (`inspect_grade_case` :83 takes
  `extra_scorers` and `named_scores`; `_outcome` :148 returns a dict of named values;
  `_score_as_float` :248; `_case_score` :169 applied to the headline only; `_check` :274 one
  Check per scorer, `id` = the registry name)
- Modify: `src/screamingface_engine_inspect/single_shot.py` (`ImportedBenchmark.aggregation`
  :171 binds the new row fields; `_FAILURE_MESSAGES` :98 wording for a named scorer failure)
- Modify: `src/screamingface_engine/benchmarks/shared_grading/benchmark_aggregation.py`
  (`CaseGradeOutcome` :108 gains `scores`; `_scored_result` :499 writes it into the grade dict
  and asserts the key set, D4)
- Test: `tests/unit/inspect/test_inspect_scorer_adapter.py`, `tests/unit/test_shared_grading_
  aggregation.py` (append)

- [ ] **Step 1 (RED):** `test_two_scorers_grade_the_same_answer_once_each` (stand-in scorers
  `f1`-like and `exact`-like on one Case → `scores == {"f1": 0.667, "exact": 0.0}`, two Checks
  in declaration order, each with the raw value as Evidence); `test_headline_score_is_the_named_
  headline_column`; `test_inverted_grade_flips_the_headline_only` (flag set → `score` and
  `scores[headline]` are `1 − grade`, the other column raw); `test_verdict_grades_map_the_
  headline_scorer_only`; `test_one_failing_scorer_fails_the_case_naming_it` (D6);
  `test_a_single_scorer_case_grade_has_no_scores_key` (unchanged path, Review Focus 5);
  `test_scored_result_refuses_a_key_set_that_differs_from_named_scores` (D4).
- [ ] **Step 2 (GREEN):** implement; stage comments mapping to the spec's §2.3.
- [ ] **Step 3:** run both test files plus `tests/unit/inspect/test_inverted_grade.py` and
  `test_verdict_grades.py` unchanged.
- [ ] **Step 4: Commit** `feat(screamingface-engine): grade a Case once per declared scorer`.

### Task 3.3: A dict-valued inspect Score becomes named scores

**Files:**
- Modify: `scorer_adapter.py` (`_score_as_float` :248 keeps its scalar contract; a new
  `_named_values` reads a `dict` value through the same closed map per key)
- Test: `tests/unit/inspect/test_inspect_scorer_adapter.py` (append)

- [ ] **Step 1 (RED):** `test_a_dict_valued_score_becomes_named_scores` (stand-in scorer
  returning `{"correct": "C", "incorrect": "I", "not_attempted": "I"}` with `named_scores`
  declared → `{1.0, 0.0, 0.0}`, headline `correct`); `test_an_undeclared_dict_key_fails_the_
  case_by_name`; `test_a_missing_declared_key_fails_the_case_by_name`;
  `test_a_dict_score_without_declared_names_fails_as_invalid_score_value` (the pre-change
  behaviour at :106 is preserved for a row that declares nothing).
- [ ] **Step 2 (GREEN):** implement.
- [ ] **Step 3: Commit** `feat(screamingface-engine): read a dict-valued inspect Score as named
  scores`.

### Task 3.4: The reducer averages every column

**Files:**
- Modify: `single_shot.py` (`_accuracy` :800 → also means each `grade.scores` column over the
  same Cases, D5; `benchmark_aggregate_async` :671 passes them to `CandidateScore`)
- Modify: `src/screamingface_engine/benchmarks/aggregation.py` (`CandidateScore` :65 gains
  `scores`; `finalize_candidate_result` :76 writes it at :144)
- Test: `tests/unit/test_benchmark_aggregation.py`, `tests/unit/inspect/` (append)

- [ ] **Step 1 (RED):** `test_the_reducer_means_each_named_column_over_graded_cases` (3 Cases,
  one failed → both columns over the 2 graded; `coverage` 0.667); `test_candidate_result_
  scores_headline_equals_score`; `test_a_single_scorer_benchmark_result_has_no_scores`.
- [ ] **Step 2 (GREEN):** implement.
- [ ] **Step 3: Commit** `feat(screamingface-engine): average every named score column`.

### Task 3.5: Row fields and Revision pins

**Files:**
- Modify: `src/screamingface_engine_inspect/benchmarks.py` (`BenchmarkSpec` :50 gains
  `extra_scorers`, `named_scores`, `dropped_scorers`, all `()` by default; `_assemble` :1625
  adds `_named_score_pins` beside `_inverted_grade_pins` :1975, emitted only when any is
  non-empty; assembly refuses `named_scores` shorter than `1 + len(extra_scorers)` or a
  `dropped_scorers` name that is also declared)
- Test: `tests/unit/inspect/test_published_revisions.py` (unchanged), a new
  `tests/unit/inspect/test_named_score_pins.py`

- [ ] **Step 1 (RED):** `test_extra_scorers_pin_into_the_revision`;
  `test_a_single_scorer_row_has_no_score_pins`; `test_a_dropped_scorer_pins_into_the_revision`;
  `test_assembly_refuses_named_scores_that_do_not_cover_the_scorers`;
  `test_assembly_refuses_a_dropped_scorer_that_is_also_declared`.
- [ ] **Step 2 (GREEN):** implement; `INVARIANT:` the pins are added only when set.
- [ ] **Step 3:** `test_published_revisions.py` passes unchanged.
- [ ] **Step 4: Commit** `feat(screamingface-engine): declare extra, named and dropped scorers
  on the row`.

### Task 3.6: Tripwire helper and the Engine round-trip twin

**Files:**
- Add: `src/screamingface_engine_inspect/scorer_metrics.py` (`headline_metric_kind(scorer) ->
  Literal["mean", "other"]` reading `registry_info` metrics names; `accuracy` / `mean` are
  plain means, `stderr` ignored, anything else "other") — the importer calls it in PR 4
- Test: `tests/unit/inspect/test_scorer_metrics.py`, `tests/unit/test_candidate_result_
  contract.py` (append)

- [ ] **Step 1 (RED):** `test_accuracy_and_mean_are_plain_means`; `test_stderr_is_ignored`;
  `test_a_custom_metric_is_other` (a stand-in `@metric` function);
  `test_a_multi_score_candidate_result_round_trips_as_payload` (Review Focus 1, Engine side).
- [ ] **Step 2 (GREEN):** implement.
- [ ] **Step 3:** `uv run .claude/scripts/run_gates.py screamingface-engine` green.
- [ ] **Step 4: Commit**, then PR-open `feat(screamingface-engine): carry named scores through
  grading (OME-1268, PR 3 of 5)` with the deploy note **after PR 2's SDK release**.

---

## PR 4 — Engine: the importer (branch `OME-1268-importer-named-scores`)

### Task 4.0: Ledger

- [ ] Create `docs/work/2026-10-08-ome-1268-importer-named-scores.md`; commit.

### Task 4.1: Keep every conservable scorer

**Files:**
- Modify: `src/screamingface_engine_inspect/importer.py` (`_scorer_reference` :590 returns the
  full list; its refusal at :596 becomes "no scorer declared" only; `_scorer_lines` :1220
  renders `scorer=` for the first conservable scorer and `extra_scorers=` for the rest,
  `named_scores=` from registry names, `dropped_scorers=` for any refused-by-name scorer with
  the reason in the description; a `TODO(review)` when the headline is not upstream's first)
- Modify: `src/screamingface_engine_inspect/import_replay.py` (:186 uses the same list)
- Test: `tests/unit/inspect/test_inspect_importer.py` (append; `render_generated_rows` tests
  unchanged)

- [ ] **Step 1 (RED):** `test_a_two_scorer_task_renders_scorer_and_extra_scorers` (a stand-in
  Task with `scorer=[f1(), exact()]` → `scorer="...f1"`, `extra_scorers=("...exact",)`,
  `named_scores=("f1", "exact")`); `test_a_self_grading_scorer_is_dropped_by_name_with_a_
  review_todo` (a stand-in scorer with `model=None` that calls `get_model` → dropped, headline
  moves to the next, TODO rendered); `test_a_task_with_no_scorer_is_refused`;
  `test_a_single_scorer_task_renders_byte_identically` (Review Focus 5).
- [ ] **Step 2 (GREEN):** implement.
- [ ] **Step 3: Commit** `feat(screamingface-engine): import every conservable scorer of a Task`.

### Task 4.2: The headline-metric tripwire

**Files:**
- Modify: `importer.py` (`_scorer_lines` calls `headline_metric_kind` on the headline scorer;
  "other" → `ImporterError("headline metric <name> is not a plain mean; declare a reducer")`;
  a non-headline scorer's non-mean metric → a `dropped_metrics` note in the description, D8)
- Test: `tests/unit/inspect/test_inspect_importer.py` (append)

- [ ] **Step 1 (RED):** `test_a_formula_headline_metric_is_refused_naming_it` (the installed
  `simpleqa` task, offline: the refusal names `simpleqa_metric`); `test_a_grouped_metric_on_a_
  non_headline_scorer_is_a_named_deviation` (a stand-in with `metrics=[accuracy(), stderr(),
  grouped(...)]` → imported, the note names the metric).
- [ ] **Step 2 (GREEN):** implement.
- [ ] **Step 3: Commit** `feat(screamingface-engine): refuse a formula headline metric by name`.

### Task 4.3: A list-of-strings target at Case Preparation

**Files:**
- Modify: `src/screamingface_engine_inspect/prepare.py` (`_validated_answer_key` :1732 accepts a
  non-empty list of non-blank strings when `has_answer_key`; `prepared_case` :1389 freezes it as
  a JSON list, D9)
- Test: `tests/unit/inspect/test_inspect_cases.py` (append; the `target is empty` tests at
  :1098 and :1102 unchanged)

- [ ] **Step 1 (RED):** `test_a_list_of_accepted_answers_is_frozen_as_a_list`;
  `test_an_empty_list_target_is_refused_by_name`; `test_a_list_with_a_non_string_is_refused_by_
  name`; `test_the_adapter_grades_against_a_list_target` (inspect's `exact` on
  `["1889", "1887–1889"]` with answer "1889" → 1.0).
- [ ] **Step 2 (GREEN):** implement.
- [ ] **Step 3:** gates green; re-run the OME-1253 sweep rows whose sole refusal was scorer
  count (`results.jsonl` on that ticket) and list the outcome in the PR body (spec §8.7).
- [ ] **Step 4: Commit**, then PR-open `feat(screamingface-engine): import Tasks with several
  scorers and list targets (OME-1268, PR 4 of 5)`.

---

## PR 5 — Engine: MATH and SQuAD (branch `OME-1268-math-squad`)

### Task 5.0: Ledger

- [ ] Create `docs/work/2026-10-09-ome-1268-math-squad.md`; commit.

### Task 5.1: Import the two rows

- [ ] Run the importer for `squad` and `math` per
  `docs/adding-an-imported-benchmark.md`; resolve every `TODO(review)` (MATH's headline is
  `expression_exact_match`, dropped `expression_equivalance` with the §2.6 reason, the
  temperature Named Deviation per D10; difficulty tier; licence lines; dataset URLs).
- [ ] Offline Case Preparation verified for both (the runbook's full-bake step).
- [ ] **Conservation tests** (spec §8.2): for each row, a fixture of 3 Cases with hand-written
  answers; assert each declared scorer's per-Case value equals inspect's own scorer's value on
  the same answer (`test_squad_named_scores_match_inspect_on_three_cases`,
  `test_math_named_scores_match_inspect_on_three_cases`), and that
  `dropped_scorers == ("expression_equivalance",)` on the MATH row.
- [ ] `test_published_revisions.py` gains the two new rows only.
- [ ] Gates green; commit `feat(screamingface-engine): import MATH and SQuAD with named scores`;
  PR-open `feat(screamingface-engine): import MATH and SQuAD with named scores (OME-1268, PR 5 of 5)`.
  This PR closes OME-1268: the close comment, the mirror `status: done`, the ledgers' outcomes.

### Task 5.2: Owner-verify (not an agent step)

- [ ] A paid smoke of each row on one Candidate; the report card shows the `scores` block with
  `f1` tagged `headline` on SQuAD and `expression_exact_match` on MATH.
