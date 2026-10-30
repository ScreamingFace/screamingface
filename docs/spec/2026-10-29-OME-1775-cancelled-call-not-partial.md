---
ticket: OME-1775
status: draft 2026-10-29 (D1–D5 decided; plan next)
date: 2026-10-29
related: OME-1307 (parent epic, E14), Q27 (the rule this spec narrows), OME-1769 (capture opt-in), OME-1687 (same principle for cost)
---

# A capture is not partial for an outcome that a replay reproduces exactly

All paths are under `apps/screamingface-engine/src/screamingface_engine/` unless they start with
`tests/`, `docs/`, `apps/` or `packages/`. Tests are under `apps/screamingface-engine/`.

## 1. Problem

A fusion capture run with one failed Case is `partial` today, but its frozen copy replays exactly.

1. A fusion sends its members in parallel. url4 is fail-fast: the first failure cancels every
   sibling still in flight (`packages/url4/src/url4/dag/executor.py:8-10, 118-121`,
   `dag/node.py:135-180`).
2. A member fails, for example with `model_token_cap`. Its answer is stored. The url4 runtime
   cancels its siblings. The gateway sees a client disconnect (499) and stores nothing for them
   (`apps/aigateway/src/aigateway/routes/chat.py:389-392`).
3. The Engine records each cancelled call as `error` (`world/connector.py:1248-1253`; tools:
   `world/web_tools.py:316-325, 338-343`).
4. `CaptureTally._lost()` forgives no outcome (Q27, `capture_outcomes.py:177-180`), so the run is
   `partial`. The SDK refuses to replay it (`packages/screamingface/src/screamingface/_replay.py:137-148`),
   and the Scoreboard serves no pinned cache for it.

The same check of every other outcome (§3) found two more outcomes that are always false `partial`
labels, and one more class that is safe in a failed Case.

## 2. Evidence (prod, 2026-10-29)

- 10 of 135 linked scores were `partial`. All 10 were fusions with failed Cases
  (7 healthbench-professional, 3 frames_oracle). Every single-model score was `complete`, and so was
  every fusion with no failed Case.
- The 7 healthbench copies hold 1 entry per key. They have no retry, no error-then-200 key, and
  occurrence 0.
- A replay of healthbench `pareto_cross` (score `22f3f25a`, copy `40bb8797`) gave the SDK verdict
  `exact`. Score 0.503 = 0.503, 525 cases, `case_digest` equal, and the same 49 `model_token_cap`
  Cases failed. The gateway logged 3073 hits, 0 misses and 3 client disconnects (the same sibling
  cancels, at replay time).

## 3. When a replay is exact

A replay gives the same score, Case count and `case_digest` when both of these are true:

- **A1. Every answer the model used is in the copy, and `find` serves that answer.** The gateway
  facts this depends on:
  - The insert runs inside the request, before the response is sent, under the copy row lock. So
    a request sent after a response was received always gets a higher `seq`
    (`apps/aigateway/src/aigateway/routes/chat.py:365-378`, `core/frozen_copy/store.py:169-187`).
  - The key digest is computed after the `cache` body field is removed. A call, its `use-cache`
    re-issue and its replay share one key (`core/request_hardening.py:230-244`,
    `core/request_cache/global_controls.py:74-80`, `store.py:55-65`).
  - `find` serves the highest-`seq` 200 at a key, else the highest-`seq` entry of any status,
    else nothing (`store.py:189-215`).
- **A2. Every call that failed in the capture fails in the replay, and url4 retries it the same
  way.** Only "failed or not" and "retryable or not" matter. The failure code and text do not:
  - A failed `;optional` subtree becomes a `SourceFailure`. Every consumer drops it or renders it
    as `""`. Its code and message never reach a prompt or a member list
    (`packages/url4/src/url4/dag/nodes/guard.py:166-168`, `dag/nodes/_shared.py:45-60`,
    `dag/nodes/group.py:180, 232`).
  - A replay miss is permanent (`world/connector.py:1289-1292, 1304-1329`; tools:
    `world/web_tools.py:138-141`). url4 `retry=` never retries a permanent failure
    (`guard.py:205-217`).
  - `case_digest` holds `[case_id, status, score]` only, with no failure codes
    (`packages/screamingface/src/screamingface/_case_digest.py:25-31`).

A call that gave the model **no answer** meets A1 trivially. It meets A2 if its failure in the
capture was not retried into an answer. A replay sends it and misses, or does not send it because an
earlier failure ended the Attempt. Either way it fails, and url4 does not retry it.

### Outcome review

| Outcome | Model used an answer | Replay | Decision |
|---|---|---|---|
| `error`, cancelled | No | Miss or not sent. No retry in either run. | Forgive in a failed Case (R1) |
| `error`, deadline before send, or tool crash | No | Miss, permanent | Forgive in a failed Case (R1) |
| `failed`, `refused` or `missing` on a non-2xx response | No (an error only) | Miss, permanent | Forgive in a failed Case (R1) |
| `failed`, `refused` or `missing` on a 2xx response | Yes | Miss, so the call fails where the capture used an answer | Keep strict (R4) |
| `ambiguous`, `max-age` re-issue, last response 2xx and `stored` | Yes, the re-issue | `find` serves the re-issue (higher `seq`, same key) | `stored` (R2) |
| `ambiguous`, retry after a connect-phase failure | Yes, the retry | The first try sent no byte, so the retry's entry is the only one | Not `ambiguous` (R3) |
| `ambiguous`, retry after a read-side loss | Yes, the retry | Exact, unless the gateway stored the lost try after the retry | Keep strict (R4) |
| `ambiguous`, every transport try lost | No | The copy may hold a 200, so the replay can succeed where the capture failed | Keep strict (R4) |
| `seal`, `open`, `local` | n/a | The copy is not sealed, does not exist, or is not trusted (Q23) | No change |

## 4. Rule

- **R1. A no-answer outcome in a failed Case does not make the run `partial`.** It must meet all
  of these conditions:
  - It gave the model no answer. That is `error`, or `failed`, `refused` or `missing` whose last
    response was not 2xx. A tool call that ran always gave the model a result, failure strings
    included, so only a tool `error` is a no-answer outcome.
  - Its Case ended failed: the final Case result, after the Attempt fold
    (`benchmarks/shared_grading/attempt_fold.py:48-94`), is not scored. Then every Attempt of the
    Case failed (D2). A run can hold one final result for each Candidate. A Case that scored for
    any Candidate in the run does not count as failed.
  - Its Case did not fail on time (owner, 2026-10-29, after review). A failure of the Case, or of
    one of its Attempts, whose code or `source_code` (at the top level of its metadata or in its
    `source_error`) is time-based (`provider_queue_timeout`, `provider_execution_timeout`,
    `caller_deadline_exceeded`, `aigateway_deadline_exceeded`, url4 `timeout`,
    `x.admission_timeout`, `x.source_timeout`) makes the Case count as one a replay may score. A
    replay serves stored answers at once, so a url4 `;t=` guard may not run out there.
  - No later call with the same lane and request digest, in the same case key, at a higher
    occurrence, gave the model an answer (the retry guard, §4.1).
- **R2. A `max-age` re-issue whose last response is 2xx is not `ambiguous` because of the re-issue.**
  Its status is the last response's `X-AIGW-Capture` value. If the last response is not 2xx, the
  call stays `ambiguous`: `find` prefers the unused first 200 to the stored error.
- **R3. A transport failure in the connect phase does not make a call `ambiguous`.** These are
  `httpx.ConnectError`, `httpx.ConnectTimeout` and `httpx.PoolTimeout` (`_NEVER_SENT`,
  `world/connector.py:153`). They prove no request byte left the Engine (OME-1220), so the gateway
  stored nothing for that try. A `ReadTimeout` from `_post_attempt`'s own `asyncio.timeout` stays
  `ambiguous` whatever the phase.
- **R4. All other outcomes keep the Q27 rule.** These include:
  - `failed`, `refused` or `missing` on a 2xx response;
  - `ambiguous` after a read-side transport loss, or with every try lost;
  - a no-answer outcome in a scored Case;
  - a no-answer outcome with no Case (case key `""`).

  The `open`, `seal` and `local` reasons do not change.

### 4.1 Why the retry guard

R1 assumes that an extra failure at replay cannot make a failed Case score. One sequence breaks
that:

1. In the capture, a call fails with a retryable error (for example `_deadline_exceeded`,
   `permanent=False`, `world/connector.py:1060-1068`, or a 429/5xx with no stored entry) and leaves
   no entry.
2. url4 `retry=` sends it again at the next occurrence, and it gives an answer.
3. That member is `;optional`.
4. A deterministic node downstream fails on that member's answer, so the Case fails. For example,
   `median@1` fails on a value that is not a number (`combine/operators/reduce.py:79`). Other
   examples are `nearest@1`, field rules and `weighted_mode@1`.

At replay, the first occurrence misses permanently and url4 does not retry it. The member is
dropped, the combine succeeds, and the Case scores. A retry that the replay does not make also moves
the occurrence of every later identical request in the same case key.

The guard removes this sequence: a no-answer outcome that a later occurrence of the same request
answered is not forgiven. A cancelled call is never retried, so the guard does not change the prod
case.

### 4.2 Why R4 stays strict

- **Answer used, not stored, in a scored Case:** the replay misses where the capture used an answer,
  so the Attempt fails and the score changes.
- **Answer used, not stored, in a failed Case:** the Case usually fails again, but the §4.1 sequence
  (an `;optional` member that is dropped at replay, and a deterministic node downstream) can make it
  score. Nothing in prod needs this exception.
- **`ambiguous` after a read-side loss:** the gateway may finish the lost try after the retry and
  store it with a higher `seq`. Then `find` serves an answer the model did not use. The gateway
  does not return the entry `seq` today, so the Engine cannot check this (§11).
- **`ambiguous` with every try lost:** the copy may hold a 200 for a call that failed in the
  capture. The replay then succeeds where the capture failed.
- **No-answer outcome in a scored Case:** a retryable no-answer failure can be retried into an
  answer in the capture, but not in the replay (§4.1). For a pure cancel in an `;optional` subtree
  this is probably safe with the guard, but nothing in prod needs it (D1d).
- **No Case:** a run-level call has no Case result to compare.

## 5. Engine changes

| # | Where | Change |
|---|---|---|
| E1 | `capture_outcomes.py:31-39` `CaptureOutcome` | Add the call's Case id (`None` when the call has no Case), its case key, its occurrence, and `answered: bool` (the model got an answer). Read the Case id from the same context as `current_case_key()` (`benchmarks/case_context.py:87-98`): the candidate Case, else the graded Case. |
| E2 | `world/connector.py:1163-1195` `_CaptureProbe` | `status()` takes `answered`. It applies R2: when `responses > 1`, not `retried`, and `answered`, it returns the last header's status. A call that returns normally always ended on a 2xx, because `_fetch_completion` calls `_raise_for_status` after each `probe.read` (`:1140-1156`). |
| E3 | `world/connector.py:902-905` `_post_completion` | Call `probe.lost_reply()` only when the failure is not `_NEVER_SENT` (R3). Update the docstring at `:888-890` and the `_CaptureProbe` docstring. |
| E4 | `world/connector.py:1243-1256`, `world/web_tools.py:316-347` | Pass the Case id, case key, occurrence and `answered` when they record an outcome. Chat: `answered` is true when `_fetch_completion` returned, false when it raised. Tool: `answered` is true for `stored` and `failed`, false for `error`. There is no other change: the `said` rule stays. |
| E5 | `capture_outcomes.py:117-180` `CaptureTally` | Keep the final result of each Case (keyed by `str(case_id)`; scored in any result wins). `_lost()` skips an outcome that meets R1, including the retry guard. With no Case results, the behavior is today's. |
| E6 | `benchmarks/aggregation.py:105` `finalize_candidate_result` | Note each final Case result in the bound tally. Every final Case result goes through this function, and the aggregation ends before the executor writes the summary attributes, so the executor does not change. |
| E7 | `capture_outcomes.py` `attributes()` | Each `capture.partial.<reason>` count includes only the outcomes that still make the run `partial`. No new attribute (D3). |
| E8 | `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` | Add a Q32 row that narrows Q27 with R1–R4. Update §5.2 items 5, 6 and 7. |

No gateway, SDK or Scoreboard change is needed. The SDK reads only `capture.status`. R2 depends on
the three gateway facts in §3 A1. A contract test pins them (§8, test 12).

## 6. Known limit: the SDK replay verdict (not changed, D4)

At replay, the sibling cancel is a race. In the prod check, no call missed. But a replay can send a
cancelled sibling before the failing member's answer ends the Attempt, and get `frozen_copy_miss`.
The Case still fails and the score does not change. But `_reproduction._classify`
(`packages/screamingface/src/screamingface/_reproduction.py:47-87`) ranks `frozen_copy_miss` first, so
the verdict is `failed`.

The owner accepts this rare false `failed` verdict (D4). No SDK change is filed.

## 7. Edge cases

| # | Case | Result |
|---|---|---|
| X1 | Fusion: one member `model_token_cap`, siblings cancelled, Case failed | `complete` (R1). This is the prod case. |
| X2 | Same, but the Case has Attempt 2, which scored | Case scored, so it stays `partial` (R4). This is conservative. |
| X3 | Cancelled call in a `;optional` subtree, and the Case scored | `partial` (R4, D1d) |
| X4 | Lost transport reply (`ambiguous`) in a failed Case | `partial` (R4) |
| X5 | Cancelled grading call in a Case whose grading failed | Case failed, so `complete` (R1). The grading case key uses Attempt 1 (`case_context.py:98`), and the Case id is the same. |
| X6 | Cancelled run-level call (case key `""`) | `partial` (R4) |
| X7 | The run fails or is stopped before its final Case results | No Case results, so today's rule applies (E6) |
| X8 | Tool call cancelled in a failed Case | `complete` (R1). Same rule as chat. |
| X9 | Tool execution crashed (not cancelled) in a failed Case | `complete` (R1). At replay the lookup misses and the Case fails again. |
| X10 | A call ran out of deadline before send, all url4 retries also failed, and the Case failed | `complete` (R1). No later occurrence answered. |
| X11 | A call ran out of deadline before send, a url4 retry at the next occurrence answered, and the Case failed | `partial` (retry guard, §4.1) |
| X12 | A provider 5xx that the gateway did not store (`failed`), Case failed | `complete` (R1) |
| X13 | A 4xx sent before the capture step (no header, `missing`), Case failed | `complete` (R1) |
| X14 | A 2xx answer too large to store (`failed`, `FrozenCopyEntryTooLarge`) | `partial` (R4), in any Case |
| X15 | `max-age` re-issue, both responses 2xx, re-issue `stored` | `stored` (R2) |
| X16 | `max-age` re-issue, re-issue `failed` | `failed` (R2). This is a 2xx answer that was not stored, so `partial` (R4). |
| X17 | `max-age` re-issue, re-issue non-2xx | `ambiguous` (R2), so `partial` |
| X18 | `ConnectError` on the first try, retry 2xx `stored` | `stored` (R3) |
| X19 | `ConnectError` on both tries | `error`, no answer. R1 applies (X10 or X11). |
| X20 | `ReadError` on the first try, retry 2xx `stored` | `ambiguous` (R4) |
| X21 | Replay run | No change. A replay records no capture outcome. |
| X22 | `max-age` re-issue after a stored 2xx hit, and the re-issue never reaches the gateway (connect-phase failure on every try, or no deadline left) | `ambiguous` (R4, review 2026-10-29). The copy holds the stale 200, which a replay serves, but the model never used it. |
| X23 | Call cancelled during its `max-age` re-issue, after it read a stored 2xx | `ambiguous` (R4, review 2026-10-29). Same reason as X22. It is not a no-answer outcome that R1 forgives. |

**Known limit (gateway insert race).** The gateway stores an entry before it responds. A call
cancelled after the insert but before the response bytes reach the Engine records `error` with no
answer, while the copy holds its 200. The Engine cannot see this. In a Case that failed because of a
sibling failure, the replay fails the Case again in the same way. It can differ only when the cancel
came from a time limit and not from a failure that a replay repeats. A Case that records a
time-based failure is never forgiven (R1); a time limit that records no failure code is not seen.

## 8. Tests

### Prior tests that change (approved 2026-10-29, D5)

- `tests/unit/test_capture_outcomes.py:53-55`, the D1 row `("chat", "error", "a")` → `partial`. It
  stays `partial` when the Case is not in the failed set. Add the new rows beside it. Do not change
  the row.
- Every prior test that asserts `ambiguous` after a connect-phase failure, or after a `max-age`
  re-issue with a 2xx `stored` last response. The plan lists them. Each changes to R2 or R3.

### New tests (RED first)

1. `test_capture_outcomes.py`: an `error` in a failed Case → `complete`, and no `capture.partial.error`.
2. `test_capture_outcomes.py`: `failed`, `refused` and `missing` with `answered=False` in a failed
   Case → `complete` (parametrized).
3. `test_capture_outcomes.py`: `failed`, `refused` and `missing` with `answered=True` in a failed
   Case → `partial` (parametrized).
4. `test_capture_outcomes.py`: a no-answer outcome in a scored Case → `partial`.
5. `test_capture_outcomes.py`: a no-answer outcome with no Case → `partial`.
6. `test_capture_outcomes.py`: `ambiguous` in a failed Case → `partial`.
7. `test_capture_outcomes.py`: the retry guard. A no-answer outcome at occurrence 0 and an answered
   outcome at occurrence 1, same lane, digest and case key, Case failed → `partial`. With a
   different digest or case key → `complete`.
8. `test_capture_outcomes.py`: no failed set given → today's result for every row (regression).
9. Connector: a chat call cancelled before any response records `error`, `answered=False`, with its
   Case id. This closes a coverage gap: no test asserts the chat cancel path today.
10. Connector: a 5xx response with `X-AIGW-Capture: failed` records `failed`, `answered=False`. A
    2xx with `failed` records `answered=True`.
11. Connector: R3. A `ConnectError` then a 2xx `stored` → `stored`. A `ReadError` then a 2xx
    `stored` → `ambiguous`.
12. Connector: R2. A `max-age` re-issue with a 2xx `stored` last response → `stored`; with a
    non-2xx last response → `ambiguous`.
13. Gateway contract (`apps/aigateway` tests): a capture and its `use-cache: false` re-issue at the
    same key store two 200 entries, and `find` serves the second. If this test already exists, the
    plan names it instead.
14. `test_frozen_copy_ambiguous.py` / `test_frozen_copy_tool_capture.py`: a cancelled tool call
    records its Case id and `answered=False`.
15. Executor: a fusion Case where member A raises `model_token_cap` and member B is cancelled, with a
    stub gateway that stores A only. The run is `complete`. Another Case in the same run scores.
16. Executor: the same, but the Case scores through `;optional` → `partial` (X3).
17. Replay with the same stub copy: the Case fails again, and the score and `case_digest` equal the
    capture's.
    The test compares the score and, for each Case, the id, status, score and failure codes.
    `case_digest` holds only `[case_id, status, score]`, so equal Case tuples give an equal digest.
    The test uses a one-Case Benchmark, because a scored MedXpert Case cannot replay (OME-1786).

## 9. Owner decisions

| # | Question | Status |
|---|---|---|
| D1 | Scope of the rule | **Decided 2026-10-29.** D1a: forgive no-answer outcomes in a failed Case, with the retry guard (R1). D1b: a connect-phase failure is not `ambiguous` (R3). D1c: a `max-age` re-issue with a 2xx last response takes that response's status (R2). D1d: no exception for a scored Case. D1e: answer-used-not-stored and read-side `ambiguous` stay strict (R4). |
| D2 | Case level or Attempt level | **Decided 2026-10-29: Case level.** |
| D3 | A separate count of the forgiven outcomes | **Decided 2026-10-29: no.** No new attribute (E7). |
| D4 | File the SDK verdict change (§6) as a client-sf sub-issue under OME-1307 | **Decided 2026-10-29: no.** Accept the rare false `failed` verdict. |
| D5 | Test change approval (§8) | **Approved 2026-10-29.** |

## 10. Open questions (for the plan)

- **Q1.** The 3 frames_oracle partials have no `evaluation_coverage` in their metadata, so their
  partial reasons are not confirmed. Their recipes use `;optional` members. If their cancelled calls
  were in scored Cases (X3), this rule does not cover them.
- **Q2 (closed).** The aggregation ends before `await task` returns in the executor, so the Case
  results are in the tally before the summary attributes are written (`runner/executor.py:1068,
  1076, 1095`). The Case id at the call and in the result are joined on `str()`
  (`benchmarks/case_context.py:32`). The plan checks that both name the same Case (T0).
- **Q3 (closed).** "Answered" is "`_fetch_completion` returned". It raises on every non-2xx after
  `probe.read` (`world/connector.py:1140-1156`), so a normal return means the last response was 2xx.

## 11. Out of scope

- **Read-side `ambiguous`.** A fix needs the gateway to return the entry `seq` (or an entry id) on
  each capture response, and a check at seal time that the `seq` the Engine used is the one `find`
  serves. This is a gateway and Engine change, so it is a separate issue.
- **Answer used but not stored.** A copy cannot replay an answer it does not hold.
- **A re-seal for the `seal` reason.** A copy whose seal reply was lost may be complete, but this
  is an operations task, not a rule change.
- The 10 prod rows. They were set to `complete` by hand on 2026-10-29 (backup
  `~/sf-backups/partial-to-complete-2026-10-29/`).
