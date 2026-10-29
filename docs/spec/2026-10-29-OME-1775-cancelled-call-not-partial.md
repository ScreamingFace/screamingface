---
ticket: OME-1775
status: draft 2026-10-29 (waiting for owner approval of D1–D5)
date: 2026-10-29
related: OME-1307 (parent epic, E14), Q27 (the rule this spec narrows), OME-1769 (capture opt-in), OME-1687 (same principle for cost)
---

# A call cancelled in a failed Case does not make a capture partial

All paths are under `apps/screamingface-engine/src/screamingface_engine/` unless they start with
`tests/`, `docs/` or `packages/`. Tests are under `apps/screamingface-engine/`.

## 1. Problem

A fusion capture run with one failed Case is `partial` today, but its frozen copy replays exactly.

1. A fusion sends its members in parallel. url4 is fail-fast: the first failure cancels every
   sibling still in flight (`packages/url4/src/url4/dag/executor.py:8-10, 118-121`,
   `dag/node.py:135-180`).
2. A member fails, for example with `model_token_cap`. Its answer is stored. The url4 runtime cancels its
   siblings. The gateway sees a client disconnect (499) and stores nothing for them
   (`apps/aigateway/src/aigateway/routes/chat.py:384-387`).
3. The Engine records each cancelled call as `error` (`world/connector.py:1157-1164`; tools:
   `world/web_tools.py:320-325, 341-345`).
4. `CaptureTally._lost()` forgives no outcome (Q27, `capture_outcomes.py:177-180`), so the run is
   `partial`. The SDK refuses to replay it (`packages/screamingface/src/screamingface/_replay.py:137-148`),
   and the Scoreboard serves no pinned cache for it.

## 2. Evidence (prod, 2026-10-29)

- 10 of 135 linked scores were `partial`. All 10 were fusions with failed Cases
  (7 healthbench-professional, 3 frames_oracle). Every single-model score was `complete`, and so was
  every fusion with no failed Case.
- The 7 healthbench copies hold 1 entry per key. They have no retry, no error-then-200 key, and occurrence 0.
- A replay of healthbench `pareto_cross` (score `22f3f25a`, copy `40bb8797`) gave the SDK verdict
  `exact`. Score 0.503 = 0.503, 525 cases, `case_digest` equal, and the same 49 `model_token_cap` Cases
  failed. The gateway logged 3073 hits, 0 misses and 3 client disconnects (the same sibling cancels,
  at replay time).

## 3. Rule

- **R1.** An outcome with status `error` (the call gave the model no answer), whose Case **ended
  failed**, does not make the run `partial`.
- **R2.** All other outcomes keep the Q27 rule. These include `failed`, `refused`, `missing` and `ambiguous`, an
  `error` in a Case that scored, and an `error` with no Case (case key `""`). The `open`, `seal`
  and `local` reasons do not change.
- **R3.** A Case "ended failed" when its final result (after the Attempt fold,
  `benchmarks/shared_grading/attempt_fold.py:48-94`) is not scored. Then every Attempt of the Case
  failed.

### Why R1 is safe

A replay can change a Case result only if it makes a failed Case score. It cannot do that here:

1. The cancelled call has no entry. If a replay sends it, the replay gets `frozen_copy_miss`, which
   is a failure (`world/connector.py:1221-1236`, `permanent=True`).
2. If the replay does not send it, then an earlier failure ended the Attempt first.
3. Either way the Case fails again. Its `case_digest` entry `[case_id, status, null]`
   (`packages/screamingface/src/screamingface/_case_digest.py:19-31`) is the same, and failed Cases are not
   in the score.
4. Attempts are fixed siblings, not retries (`benchmarks/protocol.py:124-141`). No failure code decides
   whether another Attempt runs, so a different failure code at replay cannot change which
   Attempts run.

### Why R2 stays strict

- **`ambiguous` in a failed Case:** a lost reply may have been stored as a 200. A replay would serve
  that answer, and the Case could score where the capture failed.
- **`error` in a scored Case:** this happens when a `;optional` subtree fails
  (`packages/url4/src/url4/dag/nodes/guard.py:97-135`) and the Case still scores. Downstream nodes see the
  failure. If the failure text reaches a later prompt, a different first error at replay
  (`frozen_copy_miss` instead of `model_token_cap`) changes that prompt and its digest. This spec does
  not prove that path safe.
- **`error` with no Case:** a run-level call has no Case result to compare.

## 4. Engine changes

| # | Where | Change |
|---|---|---|
| E1 | `capture_outcomes.py:31-41` `CaptureOutcome` | Add the Case id of the call (`None` when the call has no Case). Read it from the same context as `current_case_key()` (`benchmarks/case_context.py:87-98`): the candidate Case, else the graded Case. |
| E2 | `world/connector.py:1158-1165`, `world/web_tools.py:320-345` | Pass the Case id when they record an outcome. There is no other change: the `said` rule and the `ambiguous` rule stay. |
| E3 | `capture_outcomes.py:138-180` `status()`, `attributes()`, `_lost()` | Take the set of failed Case ids. `_lost()` skips an `error` outcome whose Case id is in the set. The default is an empty set, which gives today's behavior. |
| E4 | `runner/executor.py:806-830` and `:1044-1060` | Give the tally the failed Case ids from the run result before it writes the summary attributes. A failed run (`_failed_run_logs`) has no Case results, so it passes no set and keeps today's rule. |
| E5 | `capture_outcomes.py` `attributes()` | Add `capture.unused.error = <n>`: the count of R1 outcomes. This keeps them visible. `capture.partial.error` counts only the outcomes that still make the run `partial`. |
| E6 | `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` | Add a Q32 row that narrows Q27 with R1–R3. Update §5.2 items 5 and 6. |

No gateway, SDK or Scoreboard change is needed for R1. The SDK reads only `capture.status`.

## 5. Companion change (client-sf, not in this issue)

At replay, the sibling cancel is a race. In the prod check, no call missed. But a replay can send a
cancelled sibling before the failing member's answer ends the Attempt, and get `frozen_copy_miss`.
The Case still fails and the score does not change. But `_reproduction._classify`
(`packages/screamingface/src/screamingface/_reproduction.py:47-87`) ranks `frozen_copy_miss` first, so the
verdict is `failed`.

Proposed SDK rule: when the published score has a `case_digest`, a miss does not fail the verdict if
the score, the case count and the `case_digest` are all equal. In that case every missed Case failed in
both runs. With no `case_digest` (older scores), keep today's order. This needs its own client-sf
sub-issue under OME-1307 (D4).

## 6. Edge cases

| # | Case | Result |
|---|---|---|
| X1 | Fusion: one member `model_token_cap`, siblings cancelled, Case failed | `complete` (R1). This is the prod case. |
| X2 | Same, but the Case has Attempt 2, which scored | Case scored, so it stays `partial` (R2). This is conservative. |
| X3 | Cancelled call in a `;optional` subtree, and the Case scored | `partial` (R2) |
| X4 | Lost transport reply (`ambiguous`) in a failed Case | `partial` (R2) |
| X5 | Cancelled grading call in a Case whose grading failed | Case failed, so `complete` (R1). The grading case key uses Attempt 1 (`case_context.py:98`), and the Case id is the same. |
| X6 | Cancelled run-level call (case key `""`) | `partial` (R2) |
| X7 | The run fails or is stopped | No Case results, so today's rule applies (E4) |
| X8 | Tool call cancelled in a failed Case | `complete` (R1). Same rule as chat. |
| X9 | Tool execution crashed (not cancelled) in a failed Case | `complete` (R1). At replay the lookup misses and the Case fails again. |
| X10 | A Case failed only because a call was cancelled at a deadline, and that call has no entry | `complete` (R1). At replay the call misses, and the Case fails again. |
| X11 | Replay run | No change. A replay records no capture outcome. |

## 7. Tests

### Prior tests that change (owner approval required, D5)

- `tests/unit/test_capture_outcomes.py:53-55`, the D1 row `("chat", "error", "a")` → `partial`. It
  stays `partial` when the Case is not in the failed set. Add the new rows beside it. Do not change the row.

### New tests (RED first)

1. `test_capture_outcomes.py`: an `error` in a failed Case → `complete`, `capture.unused.error = 1`,
   no `capture.partial.error`.
2. `test_capture_outcomes.py`: an `error` in a scored Case → `partial`.
3. `test_capture_outcomes.py`: an `error` with no Case → `partial`.
4. `test_capture_outcomes.py`: `ambiguous`, `failed`, `refused` and `missing` in a failed Case →
   `partial` (parametrized).
5. `test_capture_outcomes.py`: no failed set given → today's result for every row (regression).
6. Connector: a chat call cancelled before any response records `error` with its Case id. This closes
   a coverage gap: no test asserts the chat cancel path today.
7. `test_frozen_copy_ambiguous.py` / `test_frozen_copy_tool_capture.py`: a cancelled tool call
   records its Case id.
8. Executor: a fusion Case where member A raises `model_token_cap` and member B is cancelled, with a stub
   gateway that stores A only. The run is `complete`. Another Case in the same run scores.
9. Executor: the same, but the Case scores through `;optional` → `partial` (X3).
10. Replay with the same stub copy: the Case fails again, and the score and `case_digest` equal the
    capture's.

## 8. Owner decisions

| # | Question | Recommendation |
|---|---|---|
| D1 | Scope of the rule | `error` outcomes in failed Cases only (R1–R2). Do not forgive `ambiguous`, and do not forgive `error` in scored Cases. |
| D2 | Case level or Attempt level | Case level (R3). The Case result is already in the run result. Attempt-level status is not, and X2 is rare. |
| D3 | Keep a count of the outcomes the rule forgives | Yes: `capture.unused.error` (E5). |
| D4 | File the SDK verdict change (§5) as a client-sf sub-issue under OME-1307 | Yes. Without it, a rare replay race reports `failed` for a correct replay. |
| D5 | Test change approval | Approve the additions in §7. No prior assertion is removed. |

## 9. Open questions

- **Q1.** The 3 frames_oracle partials have no `evaluation_coverage` in their metadata, so their
  partial reasons are not confirmed. Their recipes use `;optional` members. If their cancelled calls
  were in scored Cases (X3), this rule does not cover them.
- **Q2.** E4 needs the Case results before the summary attributes are written. The plan must confirm
  the field and the order in `runner/executor.py:1044-1060`.

## 10. Out of scope

- The `ambiguous` rule for transport retries and `max-age` re-issues. The replay lookup already
  serves the newest 200 at a key, but `seq` is insert order. That is a separate change.
- The 10 prod rows. They were set to `complete` by hand on 2026-10-29 (backup
  `~/sf-backups/partial-to-complete-2026-10-29/`).
