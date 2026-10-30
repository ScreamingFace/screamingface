---
ticket: OME-1775
stack: screamingface-engine
status: in_progress
started: 2026-10-29
---

# OME-1775 — a capture is not partial for an outcome that a replay reproduces exactly

## Intent

Stop marking a capture `partial` when the only unstored calls are sibling calls that the Engine
cancelled after their Case Attempt had already failed. Spec:
`docs/spec/2026-10-29-OME-1775-cancelled-call-not-partial.md`. Order: spec → owner approval →
plan → code.

## Evidence (2026-10-29, prod, read-only plus one $0 replay)

- 10 of 135 linked scores were `partial`. All 10 were fusions with failed cases (7
  healthbench-professional, 3 frames_oracle). Every single-model score and every fusion with no
  failed case was `complete`.
- The 7 healthbench copies: 1 entry per key, no error-then-200 key, no multi-200 key, max
  occurrence 0. So no retry caused `partial`.
- Replay of healthbench `pareto_cross` (score `22f3f25a`, copy `40bb8797`) through the SDK, with
  only the Scoreboard lookup skipped: `_classify` = `exact`. Score 0.503 = 0.503, 525 cases,
  `case_digest` equal, the same 49 `model_token_cap` case ids. Gateway: 3073 hits, 0 misses, 3
  `ClientDisconnect` (replay-time sibling cancels).
- Data fix (owner order): the 10 rows were set to `complete`. Backup:
  `~/sf-backups/partial-to-complete-2026-10-29/`.

## Log

- 2026-10-29: OME-1775 filed under OME-1307 (project ScreamingFace Q4, milestone Reproducibility
  & credit). Worktree `.claude/worktrees/ome-1775-cancelled-call-not-partial` from `origin/main`
  4909d7128. Spec drafted.
- 2026-10-29: owner decisions D2 (Case level), D3 (no new count), D5 (test changes approved).
- 2026-10-29: D4 = no SDK verdict change; accept the rare false `failed` verdict.
- 2026-10-29: owner asked for a check of every outcome for false `partial` labels. Two scouts read
  the gateway capture path and the url4 failure path. Findings: the gateway stores before it
  responds and strips `cache` from the key digest; a failed `;optional` member is dropped with no
  code or text downstream; a replay miss is permanent; `_deadline_exceeded` and 429/5xx are
  retryable. New rules: R1 widened to all no-answer outcomes in a failed Case, with a retry guard
  (§4.1, a url4 retry that the replay does not make); R2 `max-age` re-issue; R3 connect-phase
  failure. Owner accepted D1a–D1e ("yup"). Spec rewritten.
- 2026-10-29: Linear title renamed to "Do not mark a capture partial for an outcome its replay
  reproduces exactly". Plan written: `docs/plan/2026-10-29-OME-1775-replay-exact-not-partial.md`.
  Scouts confirmed one tally per run, the final Case results all pass `finalize_candidate_result`,
  and the aggregation ends before the summary. So the tally collects the Case results itself (spec
  E5/E6 changed, no executor change). Five prior tests change (R2/R3). Open: P1 (aigateway contract
  test sub-issue), P2, P3.
- 2026-10-29: owner approved the plan. P1: no sub-issue; keep the aigateway test 13 in this PR. P2: yes. P3: yes. Code starts (sdlc-python).
- 2026-10-29: T0. On every path the call-time Case id and `CaseResult.case_id` are the same
  `cases.json` row id (`$item.id`: medxpert `definition.py:145`, Inspect `single_shot.py:780`;
  `SelectedCase` is read by id). One Candidate per protocol run. If a file's row order did not
  match its ids, the call ids would fall outside the selection and nothing would be forgiven
  (the safe direction). Inspect boards aggregate `range(1, N + 1)` over a count-based prefix of
  `cases.json`, so the join holds when its ids are 1..N in row order.
- 2026-10-29: T1–T4 and test 13 by the implementer; T5 (executor tests 15–17) and T6 (design doc
  Q32 row, §5.2 items 5–7) in the main loop. Test 15 was RED before T1–T4 (`capture.partial.error
  == 2`, cancels of member-b and member-c confirmed). Test 13 (aigateway) passed before any change:
  it pins gateway behaviour that already exists.
- 2026-10-29: gates green: `run_gates.py screamingface-engine --skip-append-only` and
  `run_gates.py aigateway --skip-append-only`. The skip is for the five approved prior-test
  changes (P2); the append-only check flags only `test_frozen_copy_ambiguous.py` and
  `test_frozen_copy_calls.py`. One later aigateway run failed
  `auth/test_login.py::test_unknown_user_timing_close_to_wrong_password` (a timing test, not
  touched here; green in the gate run).
- 2026-10-29: reviews. `design-reviewer`: ACCEPT-WITH-FIXES, no structural finding. F1: a call
  cancelled during a `max-age` re-issue, after it read a stored 2xx, recorded `error` with no
  answer, so R1 could forgive it while the copy holds a 200. `sf-code-review`: the same root cause
  from the other side. A re-issue that never reached the gateway (connect-phase failure, now not
  `lost_reply` under R3) recorded `stored`; before this branch it was `ambiguous`. Fix:
  `_CaptureProbe.last_ok`; a call that raised after it read a 2xx is `ambiguous` (spec X22, X23).
  Both new tests were RED without the fix (`stored`, `error`). Also fixed: the `_lost` docstring
  (Q27 forgives no outcome), plan-local references in comments, the `status()` docstring, an
  unused counter in the T5 stub. Spec: gateway insert race recorded as a known limit.
- 2026-10-29: `.claude/test-change-approvals/OME-1775.json` added for the five approved prior-test
  changes (D5, P2), with an inline `OME-1775 (owner-approved, D5)` note at each changed line. The
  branch is renamed to `OME-1775-replay-exact-not-partial` now, because the manifest names the
  branch. Engine gates green WITH the append-only check (`--base origin/main`).
- 2026-10-29: owner decisions after review. (1) R1 skips a Case that failed on time: a failure
  whose code or `source_code` is in `TIME_BASED_CODES` (`benchmarks/failure_classes.py`) notes
  the Case as one a replay may score, so its calls are never forgiven (`sf-code-review` question;
  a url4 `;t=` guard turns wall time into a failure a replay may not repeat). Test RED first (4 of
  6 rows). Spec R1, Q32 row and design §5.2 item 5 updated. (2) File the MedXpert turn-2 replay
  defect as a separate bug in Triage.

## Deviations

- `_CaptureProbe.status(*, answered: bool = False)`: the plan had no default. A prior test
  (`test_retry_cost_of_intelligence.py:303`) calls `status()`; the default is the strict one, so
  that test needs no change.
- Test 16 uses the fusion fixture with member C made `;optional` (the quorum fixture made no model
  calls in this harness). Its count is `capture.partial.error == 2`: MedXpert has two turns.
- Test 17 (replay) uses a 1-Case Benchmark. A scored MedXpert Case cannot replay: turn 2 embeds the
  turn-1 envelope with its accounting (cost, usage, cache hits), which differs on replay, so every
  turn-2 call misses. Separate defect, reported to the owner; not filed.
