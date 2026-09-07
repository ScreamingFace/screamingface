---
ticket: OME-1037
stack: screamingface-engine + screamingface
status: in_progress
started: 2026-09-06
finished:
---

# OME-1037 — split provider refusal from graded refusal in the case status

## Intent

The case status `refused` means "provider declined" in most benchmarks but "correct
answer" in DRACO (refusing a deceptive prompt is graded as success). This unit
re-partitions the case-status space so no single status value carries both meanings:
`CaseStatus = "scored" | "failed"`. A refusal the benchmark graded is an ordinary
`scored` case carrying `refusal` text; a refusal the benchmark could not grade is a
`failed` case carrying a `provider_refusal` failure plus the grading failures.
`CandidateInvocationStatus = "completed" | "refused"` is untouched — at the
invocation layer "refused" is unambiguous (the candidate did not answer).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py`
  - `CaseStatus = Literal["scored", "failed"]` (delete `refused`).
  - Scored invariant: exactly one of `output`/`refusal` set + numeric grade + no failures.
  - Failed invariant: failures required, no numeric grade; `refusal` allowed iff
    failures include code `provider_refusal`.
  - Delete `_require_refused_case` and the now-false "no producer can emit one" WHY
    comment (~line 305) — the spine now emits `provider_refusal` failures.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py`
  - Rework/rename `refused_case_result` → `refusal_case_result`: given the grade the
    benchmark produced, classify — grade came back AND refusal text exists → scored
    case with `refusal`; otherwise → failed case with a `provider_refusal` failure
    (stage `candidate`, message "provider refused the request", retryable False)
    prepended to the grading failures, refusal text preserved as evidence, and the
    grade retained with `score=None`.
  - `grading_failure_case_result` follows the rename.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/spine/grading.py`
  - Both `refused_case_result` call sites (~164, ~204) follow the rename; the
    scored/failed classification now lives in the builder.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/draco/case_results.py`,
  `.../ifeval/aggregate.py` — call sites follow the rename (3 sites).
- `packages/screamingface/src/screamingface/case_result.py`
  - `CaseStatus` drops `refused`; `_validate_refused_case` deleted;
    scored/failed validators mirror the engine invariants (failed now ACCEPTS
    `provider_refusal` + refusal-with-provider_refusal); status derivation for
    directly-built values follows (`refusal is not None` no longer implies refused).
  - `refusal_kind` re-homed: derived for any case that represents a refusal
    (scored-with-refusal, or failed-with-`provider_refusal`), same OME-745 signal
    table (content_filter first), never serialized.
- `packages/screamingface/src/screamingface/_evaluation/results.py` — `_case_status`
  decode drops `refused`.
- `packages/screamingface/src/screamingface/_ui/report_view.py` — `refused` display
  state removed; scored-with-refusal renders as a graded case, ungradeable refusals
  land in the failed/unscored buckets.
- Detection layers UNTOUCHED: `runner/model_response.py`, `runner/connector.py`,
  `benchmarks/invocation.py`, `benchmarks/ensemble/runtime.py`.
- No schema/model (ORM) change — S1 not applicable.

## Decision (95% gate, resolved from OME-745 semantics)

A graded refusal WITHOUT refusal text cannot satisfy "exactly one of
output/refusal". Textless refusals are exactly the `content_filter` provider
declines (`raise_if_unusable` triggers on `content_filter` OR non-null refusal;
`content_filter` turns normally carry null text). A provider decline is not a model
answer, so a judge score over the empty answer is an infrastructure failure
masquerading as a graded outcome ("infrastructure failure never becomes a plausible
zero"). The builder therefore demotes it: failed case, `provider_refusal` failure,
grade retained with `score=None` (checks kept as audit evidence).

## Test plan (RED first)

- Engine contract: `refused` status rejected by `CaseResult`; scored-with-refusal
  accepted; scored with both/neither of output/refusal rejected;
  failed-with-provider_refusal (+ refusal text) accepted; failed with refusal but no
  provider_refusal code rejected; failed with numeric grade still rejected.
- Engine builder: `refusal_case_result` with graded refusal text → scored case
  carrying refusal; with score-None grade + grading failure → failed case with
  provider_refusal + the grading failure, refusal preserved; with score but no
  refusal text (content_filter decline) → failed with score demoted to None.
- SDK: decode of status `refused` raises; scored-with-refusal and
  failed-with-provider_refusal decode; `refusal_kind` truth table re-homed.
- Prior tests/goldens asserting the old `refused` case status are the contract this
  ticket deliberately changes — each one updated is listed under Deviations.
- e2e replay goldens re-blessed via the replay harness; no live calls (fixtures
  contain no refused case, so goldens are expected byte-identical).

## Acceptance

- No status value means both provider-decline and graded model refusal.
- A benchmark grades a model refusal as success without overloading failure vocabulary.
- Gates green: `run_gates.py screamingface-engine` and `run_gates.py screamingface`.
- All e2e replays green against (re-)blessed goldens; zero live model calls.

## Outcome (fill at the end — required before COMMIT)

Status note: implementation complete, gates green, draft PR open — **awaiting
review**; ledger stays `in_progress` until the PR merges and OME-1037 closes.

- **Actual files:** exactly as planned, plus the consumer sweep found three more
  surfaces (all updated in this unit):
  - Engine src: `benchmarks/contract.py`, `benchmarks/aggregation.py`,
    `benchmarks/spine/grading.py`, `benchmarks/draco/case_results.py`,
    `benchmarks/ifeval/aggregate.py` (the last two are call-site renames the plan
    grouped under "spine callers").
  - SDK src: `case_result.py`, `_evaluation/results.py`, `_ui/report_view.py`.
  - e2e harness: `tests/e2e/harness/goldens.py` (docstring only — the schema
    imports the SDK `CaseStatus`, so its vocabulary shrank automatically).
  - New tests: `apps/screamingface-engine/tests/unit/test_refusal_status_split.py`
    (10), `packages/screamingface/tests/test_refusal_status_split.py` (10).
  - Scoreboard/portal/report-intake: swept — zero consumers of the `refused` case
    status (all grep hits were unrelated prose or the invocation-layer vocabulary).
- **Commits:**
  - `fe1a8cff` — refactor(screamingface-engine): split provider refusal from
    graded refusal in case status
- **Gates:**
  - `run_gates.py screamingface-engine --skip-append-only`: ALL GATES GREEN
    (ruff check, ruff format, pyright, check_layering, pytest with coverage ≥80 —
    2350 passed, 5 skipped).
  - `run_gates.py screamingface --skip-append-only`: ALL GATES GREEN (ruff check,
    ruff format, pyright, pytest with coverage ≥95 — 1368 tests incl. the e2e
    replay suite, notebooks check, uv build, distribution check). Zero live model
    calls; committed goldens unchanged (no refusal case recorded in them).
- **Deviations:** (prior tests/goldens changed — owner-approved for this unit, they
  assert the exact contract this ticket re-partitions)
  - Engine prior tests updated (assertion flips `refused` → `scored`/`failed`,
    builder rename `refused_case_result` → `refusal_case_result`):
    `tests/unit/test_benchmark_aggregation.py`,
    `tests/unit/test_benchmark_failure_policy.py` (2 tests),
    `tests/unit/test_benchmark_outcome_conformance.py`,
    `tests/unit/test_candidate_result_contract.py`,
    `tests/unit/test_corrective_loop_e2e.py`,
    `tests/unit/test_draco_failure_integrity.py`,
    `tests/unit/test_healthbench_aggregate.py`,
    `tests/unit/test_ifeval_unscored_results.py`,
    `tests/unit/test_spine_case_grader.py`.
  - SDK prior tests updated: `tests/test_case_outcome_decoding.py`,
    `tests/test_case_refusal_kind.py` (rewritten to the two new refusal homes),
    `tests/test_candidate_result_coverage.py`, `tests/test_report.py`,
    `tests/test_report_panel.py`, `tests/test_draco_vertical_slice.py`,
    `tests/e2e/test_harness_contracts.py` (synthetic golden vocabulary),
    `tests/e2e/test_bless_contracts.py` (author_golden fixture).
  - `run_gates.py` run with `--skip-append-only` (the runner's own flag) because
    the mechanical append-only check cannot see the owner approval; every touched
    prior test is listed above.
  - Committed e2e goldens NOT re-blessed: neither committed golden
    (`draco-3pass`, `healthbench-worst30`) contains a refusal case, so replay
    outcomes are byte-identical under the new partition — verified by the e2e
    suite, zero live calls.
  - Report panel copy: the pane label `provider refusal` → `refusal` (the text may
    now be a scored model decline); a graded refusal renders a real verdict
    (correct/incorrect), no longer a warning state.
