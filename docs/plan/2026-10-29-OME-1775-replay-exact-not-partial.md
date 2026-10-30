---
ticket: OME-1775
spec: docs/spec/2026-10-29-OME-1775-cancelled-call-not-partial.md
status: approved 2026-10-29 (P1: test 13 in this PR, no sub-issue; P2, P3: yes)
stack: screamingface-engine (sdlc-python)
---

# Plan: a capture is not partial for an outcome that a replay reproduces exactly

All paths are under `apps/screamingface-engine/` unless they start with `apps/` or `docs/`.
`src/` means `src/screamingface_engine/`.

## 1. Facts this plan depends on (checked 2026-10-29)

| # | Fact | Where |
|---|---|---|
| F1 | One run has one tally, bound once in `_drive`. The Candidate runs in the same task, not as a child run. The marking tasks copy the context, but they share the tally object. | `src/runner/executor.py:1054-1058`, `src/world/candidate_adapter.py:84-86`, `src/benchmarks/shared_grading/benchmark_aggregation.py:423` |
| F2 | Every final Case result goes through `finalize_candidate_result`. It also fills a selected Case with no result as `failed` (`case_result_missing`). Both callers are final reductions, one for each Candidate. | `src/benchmarks/aggregation.py:105-165`, callers `benchmark_aggregation.py:352`, `shared_grading/incremental.py:86` |
| F3 | The aggregation ends before `await task` returns, so the Case results are in the tally before `_closing_logs` and `_record_summary` read it. | `src/runner/executor.py:1068, 1076, 1095` |
| F4 | `CaseId` is `int | str`. Results join to activity on `str()`, never on `int()`. | `src/benchmarks/contract.py:39`, `src/benchmarks/case_context.py:32` |
| F5 | A non-2xx response raises after `probe.read`. So "the call returned" means "the last response was 2xx". | `src/world/connector.py:1139-1156` |
| F6 | Tests construct `CaptureOutcome` only with positional arguments `(lane, status[, digest])`. | `tests/unit/test_capture_outcomes.py`, `tests/unit/test_frozen_copy_review_round.py` |

This replaces spec E6. The executor does not change. The tally collects the Case results itself at
F2. Spec §5 and §10 are updated in the same commit as this plan.

## 2. Design

### 2.1 `src/capture_outcomes.py`

```python
@dataclass(frozen=True, slots=True)
class CaptureOutcome:
    lane: Lane
    status: Status
    digest: str | None = None
    case_id: str | None = None   # str() of the call's Case id (F4); None: the call names no Case
    case_key: str = ""
    occurrence: int | None = None
    answered: bool = True        # the call gave the model an answer (chat: 2xx returned; tool: a result)
```

The defaults keep every prior construction valid (F6). An outcome with no `case_id` is never
forgiven, so prior tests keep today's result.

`CaptureTally` gets one field and one method:

```python
case_results: dict[str, bool] = field(default_factory=dict)
"""Per str(Case id), True when ANY final result of the run scored it (F2: one result per Candidate)."""

def _forgiven(self, outcome: CaptureOutcome, answered_at: Mapping[tuple[str, Lane, str | None], int]) -> bool:
    """R1 (spec §4): a no-answer outcome in a Case that every final result failed, that no later
    occurrence of the same request in the same case key answered."""
```

- `_forgiven` is true only when ALL of these are true:
  - `outcome.status != "ambiguous"` and `not outcome.answered`;
  - `outcome.case_id is not None` and `outcome.occurrence is not None`;
  - `self.case_results.get(outcome.case_id) is False`. A Case that is not in the dict is not
    forgiven, and a Case that scored for any Candidate is not forgiven;
  - the retry guard: `answered_at.get((outcome.case_key, outcome.lane, outcome.digest), -1) <= outcome.occurrence`.
- `answered_at` maps each key to the highest occurrence of an answered outcome. `_lost()` builds it
  once, in one pass over `outcomes`, so the check is O(n) and not O(n²). A prod run has about
  3000 outcomes.
- `_lost()` returns the outcomes that are not `stored` and not `_forgiven`. `status()` and
  `attributes()` already read only `_lost()`, so E7 (the partial counts) needs no other change.
- Update the `_lost()` docstring: Q27 still holds for every outcome except R1. Add
  `FEATURE: OME-1775` with a pointer to spec §4.

New module function, next to `record_capture_outcome`:

```python
def record_case_results(results: Iterable[tuple[object, bool]]) -> None:
    """Note each final Case result (Case id, scored) in the bound tally. A no-op when none is bound.
    A Case that scored in any result stays scored."""
```

Key: `str(case_id)`. `str(1) == str("1")`, so the int 1 and the str "1" share one key. This only
makes the rule stricter: if either one scored, the key reads scored. Add it to `__all__`.

### 2.2 `src/benchmarks/case_context.py`

Add `current_capture_case() -> tuple[str | None, str]`. It returns the call's
`(str(case id) or None, case key)`. It uses the same lookup as `current_case_key()`: the candidate
Case, else the graded Case. Change `current_case_key()` to return `current_capture_case()[1]`, so
the two can never disagree.

### 2.3 `src/world/connector.py`

- **R3, `_post_completion` (`:902-906`):** call `probe.lost_reply()` only when
  `not isinstance(exc, _NEVER_SENT)`. Update the comment and the docstring at `:888-890`: a
  connect-phase failure proves no byte was sent, so the gateway stored nothing for that try.
- **R2, `_CaptureProbe.status(self, *, answered: bool)`:** return `ambiguous` when
  `self.retried or (self.responses > 1 and not answered)`. Otherwise return the lookup of the last
  header. Update the docstring: the gateway stores before it responds (`seq` order) and strips
  `cache` from the key digest, so a re-issue that returned is the entry `find` serves.
- **E4, `_recorded_completion` (`:1236-1256`):** take `case_id, case_key = current_capture_case()`
  in place of `current_case_key()`. The success path records
  `CaptureOutcome("chat", probe.status(answered=True), digest, case_id, case_key, occurrence, True)`.
  The `except` path records the same fields with `probe.status(answered=False) if said else "error"`
  and `answered=False`. The `said` rule does not change.
- `_fetch_replay` takes only the case key, so it does not change.

### 2.4 `src/world/web_tools.py`

- `_executed` (`:316-330`): take `case_id, case_key = current_capture_case()`.
- The two `error` records (`:324`, and `:343` in `_capture_result`) pass
  `case_id, case_key, occurrence, answered=False`.
- The `stored`/`failed` record (`:345-347`) passes `answered=True`, because the model gets the
  result.
- `_capture_result` gets the `case_id` parameter. It already has `case_key` and `occurrence`.

### 2.5 `src/benchmarks/aggregation.py`

In `finalize_candidate_result`, after `typed_cases` is built, call
`record_case_results((case.case_id, case.status == "scored") for case in typed_cases)`. Add
`FEATURE: OME-1775` and one line on why (R1 needs the final result of each Case). The `benchmarks`
package already imports `capture_outcomes` (`case_context.py:8`). The layering check must stay
green.

### 2.6 Docs

- Spec: update E5 and E6 (the tally collects the results at F2; no executor change), X7 (a run that
  fails before its final results has none, so today's rule applies), and §10 (close Q2). Add a rule
  line for many Candidates: a Case that scored for any Candidate in the run is not failed.
- `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md`: add the Q32 row
  (narrows Q27 with R1–R4) and update §5.2 items 5, 6 and 7.

## 3. Tasks

| # | Task | Who | Output |
|---|---|---|---|
| T0 | **Check the Case id identity.** For the two paths that bind `case_scope` (`world/candidate_adapter.py:67` and `screamingface_engine_inspect/single_shot.py:917`, `positive_case_id(request.intent)`), confirm that the id at the call equals `str(CaseResult.case_id)` of the same Case. Also find the smallest benchmark expression that `tests/unit/test_frozen_copy_executor.py::_run` can run with a stub gateway, and a fusion form of it. **Stop and report if an id can name a different Case** (for example index vs dataset id): then R1 could forgive a call against the wrong Case. | Main loop (+ scout) | A short note in the ledger, and the fixture for T5 |
| T1 | RED: the new unit tests (§4, tests 1–8) | implementer | Failing tests |
| T2 | GREEN: §2.1, §2.2 | implementer | Tests 1–8 pass |
| T3 | RED + GREEN: §2.3, §2.4. The changed prior tests (§4.1) and tests 9–12 and 14 | implementer | Pass |
| T4 | RED + GREEN: §2.5. Test 18 | implementer | Pass |
| T5 | RED + GREEN: the executor and replay tests 15–17, with the T0 fixture | main loop | Pass |
| T6 | Docs §2.6 | main loop | Spec and design doc updated |
| T7 | Gates (§5), then `design-reviewer` with the spec as rubric, then `sf-code-review` on the branch | reviewers | Findings fixed (one round) |

The implementer gets this plan, the spec, and the exemplars: `tests/unit/test_capture_outcomes.py`
(tally tests), `tests/unit/test_frozen_copy_ambiguous.py` and `tests/unit/frozen_copy_support.py`
(`Gateway`, `stored()`, `capture_scope()`, `run_call()`) for connector tests.

## 4. Tests

### 4.1 Prior tests that change

D5 approved the class: "every prior test that asserts `ambiguous` after a connect-phase failure, or
after a `max-age` re-issue with a 2xx `stored` last response". These are the five tests:

| Test | Today | After |
|---|---|---|
| `tests/unit/test_frozen_copy_ambiguous.py:53` `test_a_call_reissued_under_a_max_age_bound_is_ambiguous` | `ambiguous`, `partial.ambiguous == 1` | `stored`, `complete`. Rename it to `..._takes_the_reissue_status`. |
| `test_frozen_copy_ambiguous.py:77` `test_a_call_whose_transport_attempt_was_retried_is_ambiguous` (ConnectError, then 200) | `ambiguous` | Change the first step to `httpx.ReadError`. The assertion stays. This keeps the read-side rule covered. |
| `test_frozen_copy_ambiguous.py:89` `test_an_error_after_a_retried_attempt_is_ambiguous_too` (ConnectError, then 400) | `ambiguous` | Change the first step to `httpx.ReadError`. The assertion stays. |
| `test_frozen_copy_ambiguous.py:104` `test_a_later_stored_call_..._never_forgives_an_ambiguous_one` | `["ambiguous", "stored"]` | Change the first step to `httpx.ReadError`. The assertion stays. |
| `tests/unit/test_frozen_copy_calls.py:114` row `(httpx.ConnectError("down"), "ambiguous")` | `ambiguous` | `"error"` (every try fails in the connect phase, and nothing was sent). Add a row `(httpx.ReadError("lost"), "ambiguous")`. |

The `tests/unit/test_capture_outcomes.py` table (`:43-85`) does not change.

### 4.2 New tests

| # | File | Test |
|---|---|---|
| 1 | `test_capture_outcomes.py` | `error`, `answered=False`, its Case failed → `complete`, no `capture.partial.error` |
| 2 | same | `failed`, `refused` and `missing` with `answered=False`, Case failed → `complete` (parametrized) |
| 3 | same | the same three with `answered=True`, Case failed → `partial` (parametrized) |
| 4 | same | no-answer outcome, Case scored → `partial` |
| 5 | same | no-answer outcome with `case_id=None` → `partial`; Case not in `case_results` → `partial` |
| 6 | same | `ambiguous`, `answered=False`, Case failed → `partial` |
| 7 | same | retry guard: no-answer at occurrence 0 and answered at occurrence 1, same lane, digest and case key, Case failed → `partial`. A different digest, or a different case key → `complete`. |
| 8 | same | `record_case_results`: a Case failed for one Candidate and scored for another reads scored → `partial`. No tally bound → no-op. |
| 9 | `test_frozen_copy_calls.py` | a chat call cancelled before any response records `error`, `answered=False`, with its `case_id`, `case_key` and `occurrence`. Check first that a `CancelledError` step works with `Gateway` (`frozen_copy_support.py:144-145`). |
| 10 | same | a 5xx with `X-AIGW-Capture: failed` records `failed`, `answered=False`. A 2xx with `failed` records `failed`, `answered=True`. |
| 11 | `test_frozen_copy_ambiguous.py` | R3: `ConnectError` then 200 `stored` → `stored`, `complete` |
| 12 | same | R2: a `max-age` re-issue whose re-issue is a stored non-2xx → `ambiguous` |
| 13 | `apps/aigateway/tests/unit/test_frozen_copy_capture.py` | **Owner decision P1.** Two captures at the same key, the second with only `cache: {"use-cache": false}` added, both 200. A replay with no `cache` field serves the second. |
| 14 | `test_frozen_copy_ambiguous.py` | a cancelled tool call records `error`, `answered=False`, with its `case_id`. A new test beside `:140`; the old test does not change. |
| 15 | `test_frozen_copy_executor.py` | a fusion Case: member A fails with `model_token_cap` (stored), member B is cancelled. Another Case scores. The run is `complete`. |
| 16 | same | the same, but the Case scores through `;optional` → `partial` |
| 17 | same | a replay of the test 15 copy: the Case fails again, and the result score and `case_digest` equal the capture's |
| 18 | `tests/unit/` aggregation test (T0 names the file) | `finalize_candidate_result` notes each final Case in the bound tally, including a `case_result_missing` Case as failed |

## 5. Gates

- `uv run pytest` on the changed and new test files, then the whole engine unit suite.
- `ruff check`, `ruff format --check`, and `pyright` for the engine. If pyright fails on untouched
  tests, run `uv sync --dev` (inspect-ai is in the venv).
- The layering check (`check_layering.py`).
- If P1 is yes: the aigateway unit test file for test 13.
- No live eval and no network. The executor tests use the stub gateway.

## 6. Risks

- **Case id identity (T0).** This is the main risk. R1 joins a call to a Case by its id. If one path
  binds an index while the result uses the dataset id, a call could be forgiven against the wrong
  Case. T0 checks this before any code.
- **A cancel that lands after a 2xx response.** `said` is false, so the call records `error`, but
  the copy holds the 200. At replay, the call can then succeed. The Case still fails, because the
  failure that caused the cancel is replayed too. This is accepted.
- **Occurrence shift after a cancelled call.** At replay, a call that is not sent does not take its
  occurrence, so a later identical request in the same case key reads an earlier one. This needs a
  second identical request after an `;optional` failure in a failed Case. The Case still fails,
  unless the §4.1 deterministic sequence of the spec also occurs. This is accepted.

## 7. Owner decisions for this plan

| # | Question | Recommendation |
|---|---|---|
| P1 | Test 13 is in `apps/aigateway`. The repo rule says one sub-issue per app. Add an aigateway test-only sub-issue (with its own small PR), or skip test 13 and cite the two existing gateway tests (`test_frozen_copy_store.py:186`, `test_frozen_copy_replay.py:147`) in the R2 comment? | Add the sub-issue. R2 depends on three gateway facts. Two have no test today: the insert before the response, and `cache` removed from the key. |
| P2 | Approve the five changed prior tests in §4.1 | Yes |
| P3 | Approve this plan, so the code can start | — |

**Decided 2026-10-29:** P1: no sub-issue for each app; test 13 stays, in this PR. P2: yes. P3: yes.

## 8. After review (owner decisions, 2026-10-29)

These changes came after the design review and the code review. The owner approved them. Where they
differ from §2, this section applies.

- **R1, the time rule.** `finalize_candidate_result` notes a Case as one a replay may score when the
  Case scored, or when the Case failed on time. A Case failed on time when a failure of the Case, or
  of one of its Attempts, has a time-based code. The check reads `code`, the top-level
  `metadata["source_code"]`, and `metadata["source_error"]` (`code` and `source_code`). The codes
  are in `TIME_BASED_CODES` (`benchmarks/failure_classes.py`). R1 never forgives a call in such a
  Case. Reason: a replay serves stored answers at once, so a url4 `;t=` guard may not run out there,
  and the Case may score.
- **A 2xx that the call did not use (spec X22, X23).** `_CaptureProbe` keeps `last_ok`: the last
  response that the call read was 2xx. `status(*, answered)` returns `ambiguous` when `retried`, or
  when the call did not return and (`responses > 1` or `last_ok`). The `said` rule in
  `_recorded_completion` includes `last_ok`. So a call that raised after it read a 2xx is
  `ambiguous`, not `error`, and R1 does not forgive it.
- **The `status()` default.** `answered` has the default `False`, the strict value, because a prior
  test (`test_retry_cost_of_intelligence.py:303`) calls `status()` with no argument. That test does
  not change.
