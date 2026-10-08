# Several Attempts per Case (PRs 3–7 of the OME-1458 stack) Implementation Plan

> **For agentic workers:** steps use checkbox (`- [ ]`) syntax. One worktree per PR; each PR is
> stacked on the one before it.

**Goal:** a Benchmark that declares `attempts=N` asks each Case N times, grades each Attempt with
its own Grading, and marks a Check met if any Attempt met it; the SDK decodes and shows the
Attempts; the AI gateway gives each unseeded Attempt its own cache entry; the inspect importer
maps any-match epochs to `attempts=N`.

**Spec:** `docs/spec/2026-10-07-OME-1458-attempts-per-case.md` (D1–D14, owner-approved). This plan
amends the spec in four places where the code says something the spec did not know (next
section); the spec is updated in the same PR (#1294) to match.

**Tech stack:** Python 3.12, uv, pytest, pydantic v2 (Engine wire models), URL4, `inspect-ai`
0.3.263.

## As built (2026-10-08)

All five build PRs are implemented and their free unit tests pass. Where the build differs from
the tasks below (each PR's ledger has the detail):

- **PR 3 (SDK):** `examples/helpers.py` is unchanged (its loader already drops operations and
  Check detail). `Benchmark.attempts` is the last field, because the dataclass is positional.
  Two prior-test changes need the owner's approval manifest: the public-surface snapshot, and
  one added line in the Engine's pinned failure-code set
  (`test_failure_classes.py::test_the_declared_vocabulary_is_exactly_the_agreed_set`, the
  OME-939 precedent).
- **PR 4 (gateway):** an Attempt-numbered request goes through a second key builder,
  `build_attempt_cache_key`, instead of an `attempt` argument on `build_global_cache_key`,
  whose parameter set is pinned to carry no caller identity. No prior test changed.
- **PR 5 (Engine egress):** the Attempt number rides in the request body from the turn loop,
  and `_fetch_completion` merges the cache policy into that `cache` object
  (`with_cache_policy`), so no call signature changed and no prior test did. `candidate_call`
  gained no `attempt` argument: PR 6 tags the Benchmark's own Candidate Invocation.
- **PR 6 (Engine fold):** a failed Candidate Invocation in any Attempt fails the whole Case
  (spec F4 and §4 say so): only `iterate` collects errors, and it rebinds `$item` and `$index`.
  The Attempts of one Case may run side by side. The declaration's tests sit in
  `test_case_attempts_contract.py`.
- **PR 7 (importer):** as planned; `test_importer_refuses_epochs.py` is the named prior-test
  change.
- **Review fixes (2026-10-08):** #1303's pane says "any of N Attempts" instead of "1 of 2
  Attempts matched" (credit is per Check, so a Case can pass while no Attempt has full marks)
  and pins that a judged Attempts Case is billed once. #1306 refuses at build an Attempt the
  rewrite cannot number, and checks every registered Benchmark asks the Attempts it declares;
  Task 6.5's probe Benchmark was not built. #1307 refuses a tuned any-match threshold and any-match
  epochs beside Named Scores. The spec's failure table gained F10 to F15 and §4 five limitations.

## What the code changed in the spec

| # | Spec said | Code says | Plan does |
|---|---|---|---|
| A1 | the fold lives in the per-Case envelope, `graded_answer.py` (⑧) | no Case Grade exists there: the envelope carries opaque Benchmark records, and every Benchmark family builds its Case Grades later, in the shared marking room `BenchmarkAggregation` (`shared_grading/benchmark_aggregation.py:362`) | ⑧ is `benchmark_aggregation.py`: each Attempt runs the existing ladder and `grade_case`, then the fold builds the Case's result from the N per-Attempt results |
| A2 | the new failure code `attempt_grade_not_pass_fail` ships in the SDK PR, the Engine PR emits it | the SDK and Engine failure-code lists are pinned equal by a twin test on each side (`test_failure_code_conformance.py`) | PR 3 adds the code to **both** lists (one Engine line); the Engine emits it from PR 6 |
| A3 | PR 5 is the whole Engine build and "may split" | the Engine build is ~500 source lines plus ~650 test lines, over the ~500-line review cap | PR 5 is the egress (④ ⑤), PR 6 the loop, fold and wire (① ③ ⑧ ⑨); the importer mapping becomes PR 7. The stack is 7 PRs; #1294 and #1295 are retitled "of 7" |
| A4 | the run's cost includes every Attempt | the SDK's per-Case accounting refuses two records for one operation in one Case (`accounting.py:192`, "duplicate accounting operation") | under Attempts each Attempt carries its own `operations`, the Case-level `operations` is absent, and the SDK sums accounting rows per Attempt |

## Decisions taken in this plan (owner can flip any before the PR that carries it)

| # | Decision | Why | Flip means |
|---|---|---|---|
| P1 | **The Attempt number travels as an `attempt` param on the Candidate Invocation**, absent on Attempt 1; the Candidate adapter strips it before the policy check and opens an Attempt scope (a context variable beside the Case scope) | params are the Engine's own call metadata, never model input; Attempt 1 renders byte-identical, so no published Benchmark's URL4 moves | an `attempt` key in the `case-v1` envelope (the envelope sits beside model input, and every Benchmark's context would need a second shape) |
| P2 | **Attempt i ≥ 2 gets a derived seed when the run's answer seed applies to the call, and the cache control `{"attempt": i}` otherwise** — including a call that pins its own seed | the spec's two rows (D5), plus the case the spec missed: a Candidate that pins `seed` itself would send Attempt 2 the same seed and be served Attempt 1's stored reply | "otherwise" narrowed to "the run declared no seed" (then a self-seeded Candidate's Attempts are copies) |
| P3 | **The derived seed is the first 31 bits of `sha256("<seed>:attempt:<i>")`** as a non-negative integer | deterministic (a rerun derives the same seed), different per Attempt, and inside every provider's seed range | `seed + i` (collides between runs seeded `s` and `s + 1`) |
| P4 | **N Attempts are N sibling `case-execution.v1` envelopes inside one `case-attempts.v1` envelope** `{schema, case_id, attempts: [...]}`; a failed Attempt is a url4 `{"error": ...}` entry in its slot | the reader files one row per Case today; one wrapper keeps that, and each Attempt keeps the envelope the ladder already understands | a list of envelopes per Case position (breaks "position is identity") |
| P5 | **The folded Check:** outcome `MET` if any Attempt met it, score 1.0 or 0.0, evidence from the first Attempt that met it (else Attempt 1), metadata `met_by_attempts: [i, …]`. Check ids must match across graded Attempts | the ARC rule (§2.4); evidence from the Attempt that earned the point is what a reader wants to see | union of all Attempts' evidence (duplicates judge evidence and its cost) |
| P6 | **Case score = met Checks ÷ Checks; metrics = the shown Attempt's** (the first with the highest folded contribution: the highest own Case score); a Benchmark with Named Scores and Attempts fails the Case as a contract error | the spec's fold; Named Scores have no per-Check meaning to fold, and no Benchmark declares both | a per-column fold for Named Scores (no Benchmark needs it) |
| P7 | **Every Attempt failed → the Case Result is Attempt 1's failed result**, carrying the `attempts` list | the Failure Policy then applies exactly as for a one-Attempt failure (F5) | a new "all Attempts failed" code (the per-Attempt failures already say why) |
| P8 | **`CaseAttempt` on the wire:** `{attempt, status, output, finish_reason, refusal, grade, failures, operations}`, `operations` omitted when absent | everything a reader needs per Attempt (D9) and nothing the Case already shows once | a full nested `CaseResult` per Attempt (repeats `case_id`, `input`, `metadata` N times) |

## Global constraints

- **Worktrees** (repo remote is `upstream`), each off the PR before it:
  `git worktree add .claude/worktrees/OME-1458-prK-<slug> -b OME-1458-prK-<slug> <base>`.
  Titles end `(OME-1458, PR k of 7)`; bodies say `Refs` and only PR 7 says `Closes`.
- **Free tests only.** Engine: `uv sync --dev --inexact` then `uv run pytest tests/unit -q` and
  extra-less `uv run pyright` (the CI lane); the inspect lane `uv run --extra inspect pytest
  tests/unit/inspect -q` for PR 7. SDK: `uv sync --extra notebook --inexact`, `uv run pytest`.
  Gateway: `uv run pytest -m "not live and not needs_postgres"`. Nothing touches a model or the
  network. Paid runs are the owner's.
- **Gates** once per PR before push: `uv run .claude/scripts/run_gates.py <stack>` (the Engine's
  pre-push hook runs it; SDK and gateway by hand).
- **Tests are append-only.** Two prior-test edits are known now and need the owner's approval
  manifest under `.claude/test-change-approvals/OME-1458.json`, asked for by name in the PR body:
  the SDK public-surface snapshot (PR 3, `CaseResult.__init__` gains `attempts`) and the
  gateway's `test_the_mvp_has_no_variant_dimension` only if its assertion stops holding (PR 4;
  the plan keeps it holding).
- **Byte-identity for N = 1** is the blast-radius guarantee: `test_published_revisions.py`, the
  pinned URL4 hashes (`test_benchmark_protocol.py:285`) and the gateway key goldens
  (`test_chat_global_cache_key_parity.py`) pass unchanged in every PR.
- Glossary words (`CONTEXT.md`): Attempt, Case, Case Grade, Check, Candidate Invocation, Case
  Result, Headline Score. "attempt" already names three other things in code (the inspect
  envelope's `attempts`, `attempt_records_endpoint`, activity retries): new symbols say
  `case_attempt` where a bare `attempt` would be ambiguous.
- Plain `test_` functions; type every argument, return and non-obvious local; one-line intuition
  docstring per function; `WHY:` / `INVARIANT:` anchors. Stage explicit paths. No
  `Co-Authored-By`.
- **Deploy order:** PR 3's SDK releases before PR 6's Engine deploys (the SDK decoder refuses the
  unknown `attempts` key, F8). PR 4's gateway before PR 5's Engine only decides when reruns are
  free (F9).

---

## PR 3 — SDK: decode, account and show Attempts (`packages/screamingface`)

Branch `OME-1458-pr3-sdk-attempts`, stacked on #1295. Box ⑪, rows F8.

### Task 3.1: `CaseAttempt` and `CaseResult.attempts`

**Files:** modify `src/screamingface/case_result.py` (`CaseResult` :324, `__init__` :341,
`to_dict` :470); test `tests/test_case_attempts.py` (new).

- [ ] RED: `test_a_case_result_without_attempts_is_unchanged` (default `attempts is None`;
  `to_dict` has no `attempts` key); `test_case_attempts_keep_their_order_and_grades`;
  `test_attempt_numbers_must_run_from_one_without_gaps` (`[1, 3]` raises `ValueError`);
  `test_a_single_attempt_list_is_refused` (N = 1 is spelled by absence).
- [ ] GREEN: frozen slots `CaseAttempt(attempt, status, output, finish_reason, refusal, grade,
  failures, operations)` reusing `CaseGrade`, `Failure`, `CaseOperation`; `attempts:
  Sequence[CaseAttempt] | None = None` keyword on `CaseResult`, `to_dict` emits only when set.

### Task 3.2: decode `attempts` from the run result

**Files:** modify `src/screamingface/_evaluation/results.py` (`_case_result` :320, optional keys
:322-342); `examples/helpers.py` (`load_candidate_result`); test `tests/test_case_attempts.py`.

- [ ] RED: `test_case_result_decodes_an_optional_attempts_key`;
  `test_an_unknown_key_inside_an_attempt_is_refused` ("unsupported field");
  `test_attempts_round_trip_through_report_json`.
- [ ] GREEN: `optional={"operations", "attempts"}`, `_case_attempt` sub-decoder with its own
  strict `_keys`.

### Task 3.3: per-Attempt accounting

**Files:** modify `src/screamingface/accounting.py` (`_rows` :242, `_candidate_rows` :187,
`_grading_rows` :217); test `tests/test_case_attempts.py`.

- [ ] RED: `test_a_case_with_attempts_is_billed_once_per_attempt` (two Attempts, one operation
  each → two generation rows, no "duplicate accounting operation");
  `test_case_level_rows_are_not_counted_again_under_attempts`.
- [ ] GREEN: when `case.attempts` is set, rows come from each Attempt's operations and grade,
  never from the Case-level fields. `WHY:` the folded Case Grade's evidence is a view of an
  Attempt's evidence; counting both bills one judge call twice.

### Task 3.4: the Report shows Attempts; the catalogue shows "any of N Attempts"

**Files:** modify `src/screamingface/_ui/report_view.py` (`_pane_html` :735, beside
`rounds_html` :768); `src/screamingface/_engine/catalog_contract.py` (`_benchmark_entry` :126)
and the catalogue display (`discovery.py:395`); tests `tests/test_case_attempts.py`.

- [ ] RED: `test_the_case_pane_says_how_many_attempts_matched` ("1 of 2 Attempts matched");
  `test_a_failed_attempt_is_counted_on_the_pane` ("1 of 2 Attempts failed");
  `test_each_attempt_answer_is_listed_under_the_case`;
  `test_a_case_without_attempts_renders_byte_identical`;
  `test_the_catalogue_shows_any_of_n_attempts` (an entry with `attempts: 2` →
  "any of 2 Attempts · 2 Candidate Invocations per Case"; absent → nothing).
- [ ] GREEN: the badge and a per-Attempt block in the pane; `attempts: int = 1` on the
  catalogue entry.

### Task 3.5: the failure code, both lists

**Files:** modify `src/screamingface/_report_primitives.py` (:22) and
`apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py` (:54); test
`tests/unit/test_attempt_failure_code.py` (new, the `test_gateway_internal_error_code.py` shape).

- [ ] RED: `test_attempt_grade_not_pass_fail_is_a_declared_code`.
- [ ] GREEN: one line in each list; both twin conformance tests stay green unchanged.

### Task 3.6: public surface, CHANGELOG, gates

- [ ] Regenerate `tests/public_surface_snapshot.json` (`UPDATE_SURFACE_SNAPSHOT=1`). **Prior-test
  change: named in the PR body for the owner's approval.**
- [ ] CHANGELOG "Unreleased": the `attempts` key, and "an older SDK refuses a report with
  Attempts: upgrade before running an Attempts Benchmark".
- [ ] `run_gates.py screamingface`; ledger `docs/work/2026-10-08-attempts-sdk.md` closed in the PR.

---

## PR 4 — AI gateway: each Attempt gets its own cache entry (`apps/aigateway`)

Branch `OME-1458-pr4-gateway-attempt-cache`, stacked on PR 3 (independent code; stacked to keep
one line). Box ⑥, rows F3, F9; acceptance 4 and 5.

### Task 4.1: the control grammar accepts `attempt`

**Files:** modify `src/aigateway/core/request_cache/global_controls.py` (`GlobalCacheControls`
:41, `parse_global_cache_controls` :61); test `tests/unit/test_global_cache_controls.py`
(append).

- [ ] RED: `test_an_attempt_number_participates_and_is_carried` (`{"attempt": 2}` →
  `participate=True, attempt=2`); `test_attempt_one_is_refused_as_malformed` (Attempt 1 is
  spelled by absence, so two spellings can never key two entries);
  `test_a_non_integer_attempt_is_malformed` (`"2"`, `True`, `2.0`, `0`);
  `test_attempt_combines_with_an_opt_out` (`{"use-cache": false, "attempt": 2}` → opted out);
  `test_the_cache_object_is_still_stripped_with_an_attempt`.
- [ ] GREEN: `attempt: int | None = None` on the dataclass; the closed set becomes
  `{use-cache, attempt}`; validation in a helper (ruff `max-returns=8`).

### Task 4.2: the key carries the Attempt number only when present

**Files:** modify `src/aigateway/core/request_cache/global_keys.py` (`GlobalChatCacheKey` :127,
`_canonical_mapping` :180, `build_global_cache_key_dto` :218, `build_global_cache_key` :257),
`core/request_cache/global_plan.py` (:135); tests `tests/unit/test_global_cache_key.py`,
`tests/unit/test_chat_global_cache_key_parity.py` (append).

- [ ] RED: `test_a_request_without_attempt_hashes_exactly_as_before` (the three pinned digests,
  recomputed through the new code path); `test_attempt_two_keys_a_different_entry`;
  `test_the_same_attempt_keys_the_same_entry_on_a_rerun`; a fourth pinned digest for
  `attempt: 2`; `test_the_attempt_member_is_absent_from_the_material_when_unset`.
- [ ] GREEN: `attempt: int | None = None` on the key; `_canonical_mapping` adds `"attempt"`
  only when set; `KEY_REVISION` unchanged. `INVARIANT:` absent means today's hash.
  `test_the_mvp_has_no_variant_dimension` keeps holding (no `variant` member).

### Task 4.3: through the route

**Files:** test `tests/unit/test_chat_global_cache_route.py` (append).

- [ ] RED/GREEN: `test_attempt_two_is_not_served_attempt_ones_stored_reply` (store the
  `attempt`-less reply `41`; the same request with `{"attempt": 2}` misses and dispatches) —
  acceptance 4; `test_a_rerun_of_attempt_two_is_served_its_own_stored_reply` (second identical
  request hits, provider called once) — acceptance 5; `test_the_provider_never_sees_the_cache_object`.

### Task 4.4: docs and gates

- [ ] `DEPLOYMENT.md:243` and the chart README's grammar line name `attempt`.
- [ ] `run_gates.py aigateway`; ledger `docs/work/2026-10-08-attempts-gateway-cache.md` closed.

---

## PR 5 — Engine egress: Attempt 2 is never a copy of Attempt 1 (`apps/screamingface-engine`)

Branch `OME-1458-pr5-engine-attempt-egress`, stacked on PR 4. Boxes ④ ⑤, row F3. Paths below are
relative to `apps/screamingface-engine/src/screamingface_engine/`.

### Task 5.1: the Attempt scope

**Files:** modify `benchmarks/case_context.py` (sibling context variable and
`case_attempt_scope(i)` / `current_case_attempt()`); `world/candidate_adapter.py`
(`_CandidateInvocation.__call__` :43, `_candidate_policy` :82); `benchmarks/definition.py`
(`candidate_call` gains `attempt: int | None = None`); test `tests/unit/test_case_attempt_scope.py`
(new).

- [ ] RED: `test_no_attempt_param_means_no_attempt_scope` (Attempt 1 and every existing call);
  `test_the_attempt_param_opens_an_attempt_scope`; `test_the_attempt_param_is_not_a_policy_param`
  (no `candidate_policy_invalid`); `test_attempt_one_or_garbage_is_a_contract_error`;
  `test_candidate_call_renders_byte_identical_without_attempt`.
- [ ] GREEN: strip `attempt` beside `context_format`, validate an int ≥ 2, open the scope inside
  `case_scope`.

### Task 5.2: the derived seed or the cache control on Attempt 2 and later

**Files:** modify `world/request_parameters.py` (`derive_attempt_seed`, beside
`apply_answer_seed` :86); `world/connector.py` (:355-373 seed site, :870-893 cache body);
`world/cache.py` (an `attempt_body_field(policy, attempt)` beside `policy_to_body_field`, docstring
invariant restated: `use-cache` from the policy, `attempt` only for Attempt 2 and later); test
`tests/unit/test_attempt_egress.py` (new, `_MockAigateway` style from
`test_answer_seed_threading.py:282`).

- [ ] RED: `test_attempt_one_sends_todays_request_byte_for_byte` (seeded and unseeded);
  `test_an_unseeded_attempt_two_carries_its_number_in_the_cache_control_only`;
  `test_a_seeded_attempt_two_carries_a_derived_seed_and_no_cache_attempt`;
  `test_the_derived_seed_is_stable_and_differs_per_attempt`;
  `test_a_self_seeded_candidate_attempt_two_carries_the_cache_attempt` (P2);
  `test_an_opted_out_run_keeps_its_opt_out_beside_the_attempt`;
  `test_a_judge_call_never_carries_the_attempt` (grading is outside the Candidate Invocation);
  `test_the_reissue_path_keeps_the_attempt`.
- [ ] GREEN: the two rules of P2, applied only inside `in_candidate_invocation()`.
  `test_runner_cache_body_field.py` stays unchanged (it tests `policy_to_body_field`, which keeps
  its `use-cache`-only output); `README.md:350-356` restated.

### Task 5.3: gates

- [ ] Extra-less `pyright` + `pytest tests/unit`; push through the hook; ledger
  `docs/work/2026-10-08-attempts-engine-egress.md` closed.

---

## PR 6 — Engine: ask, grade and fold N Attempts (`apps/screamingface-engine`)

Branch `OME-1458-pr6-engine-attempt-fold`, stacked on PR 5. Boxes ① ③ ⑧ ⑨, rows F4–F6;
acceptance 1, 2, 3, 7.

### Task 6.1: the declaration

**Files:** modify `benchmarks/definition.py` (`BenchmarkDeclaration` :136, `as_block` :185); test
`tests/unit/test_benchmark_attempts_declaration.py` (new).

- [ ] RED: `test_attempts_defaults_to_one_and_stays_out_of_the_block`;
  `test_attempts_above_one_is_published_in_the_block`;
  `test_attempts_below_one_or_not_an_int_is_refused`.
- [ ] GREEN: `attempts: int = 1` with a `WHY:` on the one default in a no-defaults record (the
  `origin` precedent, :223).

### Task 6.2: the Attempt loop in the expression

**Files:** modify `benchmarks/protocol.py` (`preserve_candidate_outcome` :12 gains
`attempts: int = 1`); `benchmarks/graded_answer.py` (the `case-attempts.v1` envelope route and
decoder); test `tests/unit/test_case_attempts_protocol.py` (new, the stub-endpoint style of
`test_benchmark_protocol.py:233`).

- [ ] RED: `test_one_attempt_renders_byte_identical` (the pinned hashes stay; a direct render
  comparison); `test_two_attempts_invoke_the_candidate_twice_in_order` (stub replies `41`, `42`);
  `test_attempt_two_carries_the_attempt_param`; `test_bindings_rerun_for_every_attempt`;
  `test_a_failed_attempt_keeps_its_slot_and_the_case_still_runs` (F4).
- [ ] GREEN: N = 1 returns today's expression untouched; N > 1 builds N copies of today's
  `case_execution`, each wrapped in its own collecting iterate, Attempt i's invocation with
  `attempt=i` appended (i ≥ 2), joined by the `case-attempts` route into one envelope.

### Task 6.3: the fold in the marking room

**Files:** modify `shared_grading/case_grades.py` (`_file_case_grade` :175 files an attempts
envelope as N per-Attempt rows); `shared_grading/benchmark_aggregation.py` (`case_result` :362
grades each Attempt through the existing ladder and `grade_case`, then folds); new
`shared_grading/attempt_fold.py` (the pure fold); test `tests/unit/test_attempt_fold.py` (new).

- [ ] RED (the fold is pure, so most tests need no URL4):
  `test_one_check_any_attempt_met_scores_one` (41 then 42 → 1.0, shown answer 42);
  `test_two_checks_met_by_different_attempts_score_one` (grid A by Attempt 1, grid B by Attempt
  2 → 1.0, the ARC rule, acceptance 3); `test_the_shown_answer_is_the_first_best_attempt`;
  `test_a_partial_check_fails_the_case_as_attempt_grade_not_pass_fail` (F6, acceptance 7);
  `test_a_failed_attempt_is_kept_and_the_case_is_graded_from_the_rest` (F4);
  `test_every_attempt_failed_is_attempt_ones_failure_with_the_attempts_list` (F5, P7);
  `test_check_ids_that_differ_across_attempts_are_a_contract_error`;
  `test_named_scores_with_attempts_fail_the_case` (P6);
  `test_a_folded_check_records_which_attempts_met_it`;
  `test_case_operations_move_onto_each_attempt` (A4).
- [ ] GREEN: `fold_case_attempts(results: Sequence[CaseResult]) -> CaseResult`, Feynman docstring
  with the grid A/B worked example.

### Task 6.4: the wire field

**Files:** modify `benchmarks/contract.py` (`CaseAttempt` model, `CaseResult.attempts` :262 with
`exclude_if` like `operations` :278); test `tests/unit/test_case_attempts_contract.py` (new).

- [ ] RED: `test_attempts_is_absent_from_the_payload_when_unset`;
  `test_a_case_attempt_round_trips_the_sdk_decoder` (the Engine payload decodes through PR 3's
  `_case_result`, the OME-1268 twin pattern); `test_attempt_numbers_run_from_one`.
- [ ] GREEN: the model and validators.

### Task 6.5: the test-only Benchmark, end to end

**Files:** test `tests/unit/test_attempts_end_to_end.py` (new): an inline probe Benchmark (the
`test_benchmark_inverted_grade.py:29` factory style) declaring `attempts=2`, stub Candidate
replies `41` then `42`, run through the Engine's URL4 node to the finalized Candidate Result.

- [ ] RED/GREEN: `test_an_attempts_benchmark_scores_the_any_match_number` (Case score 1.0, two
  Attempts on the Case Result, Headline Score 1.0) — acceptance 2;
  `test_existing_benchmarks_are_byte_identical` (the published revisions and pinned hashes,
  run unchanged) — acceptance 1.
- [ ] Gates through the hook; ledger `docs/work/2026-10-08-attempts-engine-fold.md` closed.

---

## PR 7 — Engine: the importer maps any-match epochs (`screamingface_engine_inspect`)

Branch `OME-1458-pr7-importer-maps-epochs`, stacked on PR 6. Box ②, rows F1 → F2; acceptance 6.
Closes OME-1458.

### Task 7.1: map or refuse

**Files:** modify `src/screamingface_engine_inspect/importer.py` (`_refuse_several_epochs` :99
becomes `_task_attempts(task) -> int`, refusing every reducer that is not any-match);
`import_replay.py` (`TaskReplayFacts` :81 gains `attempts`); `task_replay_rows.py`
(`_benchmark_row_lines` :309 writes `attempts=N,` only when N > 1); `benchmarks.py`
(`BenchmarkSpec.attempts`, an `_attempts_pins` beside `_inverted_grade_pins` :4309);
`single_shot.py` (`BenchmarkDeclaration(attempts=…)` :360, `preserve_candidate_outcome(attempts=…)`
:511); test `tests/unit/inspect/test_importer_refuses_epochs.py` (append).

- [ ] RED: `test_any_of_two_maps_to_two_attempts` (`Epochs(2, "pass_at_2")`, `max`,
  `at_least_1`); `test_pass_at_one_of_five_is_refused_naming_the_reducer`;
  `test_mean_epochs_are_refused_naming_the_reducer`; `test_a_custom_reducer_is_refused`;
  `test_attempts_pin_into_the_revision_only_above_one`; the one-epoch stand-ins stay as they are.
- [ ] GREEN. The existing refusal test of `any_of_two` (PR 2) asserted a refusal and now maps:
  **prior-test change, named in the PR body for the owner's approval.**

### Task 7.2: close

- [ ] Spec status `implemented`; `docs/tasks/2026-10-02-OME-1458-attempts-per-question.md`
  `status: done`, `closed:`; every ledger outcome filled; `Closes OME-1458` in the body.
- [ ] Owner-verify (not an agent step): release the SDK, deploy the gateway, deploy the Engine,
  then one paid run of an Attempts Benchmark twice to watch rule 3 hold (OME-1476 is the real one).

## Review focus

1. **N = 1 never moves**: every PR's byte-identity tests (published revisions, pinned URL4
   hashes, gateway key goldens, Attempt 1's request).
2. **Attempt 2 is never served Attempt 1's reply** — PR 4's route test and PR 5's egress tests,
   both sides of the wire.
3. **The fold is per Check**, pinned by the grid A/B test in PR 6.
4. **A judge is never re-keyed by an Attempt** — PR 5's judge test.
5. **Cost counts every Attempt exactly once** — PR 3's accounting tests against PR 6's payload.
