# Plan — SDK run isolation (OME-1071, OME-1067, OME-1066)

Status: approved (user order: "spec + plan, then code"). Spec:
`docs/spec/2026-09-28-sdk-run-isolation.md`. Language: ASD-STE100.
Stack: `screamingface` (`packages/screamingface`). No Engine change (spec E1).

## Order and why

A stack of branches. Each unit is green alone and adds only its own diff.

| Unit | Branch (base) | Ticket | Content |
|---|---|---|---|
| 1 | `sdk-run-isolation-stop-one` (`origin/main`) | OME-1071 | spec + plan; `_stop_own_run`; C2 → stop one Run; B1 abort flag reset |
| 2 | `sdk-run-isolation-disconnect` (unit 1) | OME-1067 | C3 → stop one Run; B2 retire a completed Run |
| 3 | `sdk-run-isolation-submit-retry` (unit 2) | OME-1066 | 503 + `Retry-After` retry of run start; notices; B3 |
| 4 | `sdk-run-isolation-evaluation-outcome` (unit 3) | OME-1071 (+1067 acceptance) | runner C1 classification + Partial Report — **waits for Q1, Q2, Q3** |

WHY the runner change moved from unit 1 to unit 4: it needs two owner answers (a prior
test must change, and a public shape must be chosen). Everything in units 1-3 is correct
for every answer to Q1-Q3, so it can land first. The runner change touches only
`_evaluation/runner.py` (+ the result assembly), not the transport, so putting it on top
needs no restack.

Units 1-3 change the transport only. Until unit 4 lands, a multi-Candidate Evaluation still
stops every Run when one Candidate raises (C1). The transport-level fixes are visible for
direct transport use, single-Candidate Evaluations, B1 (every later Run on a Client after a
sweep), and OME-1066 (a start now waits instead of failing, so C1 does not fire).

## Unit 1 — stop one Run (OME-1071, transport half)

Ledger: `docs/work/2026-09-28-sdk-run-isolation-stop-one.md`.

1. RED — new stub `tests/_isolation_engine.py`: a real HTTP + WebSocket stub that serves
   SEVERAL Runs, each by its Candidate URL4 (plan per Run: first stream, reconnect script,
   start answers, a hold event). It records each `DELETE /` capability.
2. RED — new `tests/test_run_isolation.py` (sync + async):
   - Two Runs on ONE transport. Run A: reconnect refused with a non-Access 401. Run B:
     healthy, held open until A fails. Expect: A raises `websocket_disconnected`; B
     completes; the only `DELETE /` is A's capability.
   - B1: `cancel_active()` once, then a new Run whose stream drops with 1012 reconnects and
     completes (today it fails at once with no `DELETE /`).
3. GREEN — `_engine/transport.py`, both twins: `_stop_own_run(token)`; C2 calls it;
   `run()` clears `_aborted` when it starts with no active Run.
4. Gates, ledger outcome, commit (spec + plan commit first).

## Unit 2 — a lost stream stops only its own Run (OME-1067)

Ledger: `docs/work/2026-09-28-sdk-run-isolation-disconnect.md`.

1. RED (sync + async):
   - Two Runs on one transport. Run A: stream lost, every reconnect refused with 503,
     budget 0.3 s. Run B healthy, held. Expect: A `websocket_disconnected`; B completes;
     only A's capability is deleted.
   - B2: Run A reaches its terminal frame with an artifact result; the artifact fetch is
     held; a `cancel_active()` during the fetch sends no `DELETE /` for A, and A still
     returns its outcome.
2. GREEN — `_sweep_after_disconnect(token)` stops one Run (name kept: prior tests patch
   it); `_back_off` / `_on_stream_failure` pass the capability; retire the capability when
   the outcome is accepted.

## Unit 3 — retry a start the Engine did not admit (OME-1066)

Ledger: `docs/work/2026-09-28-sdk-run-isolation-submit-retry.md`.

1. RED — `tests/test_admission_retry.py`:
   - Policy unit tests (fake clock): delta-seconds, HTTP-date, absent/invalid header →
     jitter backoff, `Retry-After: 0` floor, the last wait is cut to the deadline, expiry.
   - Real stub (sync + async): 503 twice then 202 → the Run completes; 503 with
     `Retry-After: 1` waits about 1 s; 503 forever → `engine_at_capacity` with status 503
     and a capacity message; 500 → fails at once (today's behavior); a sibling Run
     completes while A waits and nothing is deleted; a listener gets
     `waiting_for_capacity` (attempt 1, 2) then `admitted`; `cancel_active()` during a wait
     ends it at once with no further start.
   - Renderers: terminal lines and notebook row text for the two new states.
2. GREEN — new `_engine/admission.py` (policy); `_start_sync/_start_async` take an
   optional policy + notice callback (the old call shape stays valid);
   `_core/ports.py` `_ConnectionState` gets `waiting_for_capacity` / `admitted`;
   `_evaluation/progress.py`, `_ui/evaluation_state.py` render them.

## Unit 4 — Evaluation outcome (waits for owner)

After Q1-Q3: runner C1a/C1b/C1c split, wait for siblings, Partial Report per Q2, the pinned
test replaced per Q1, regression pin for KeyboardInterrupt / cancellation sweep.

## Gates (every unit)

`uv run .claude/scripts/run_gates.py screamingface --base origin/main` green (95 %
coverage). Units 2 and 3: `git diff <previous-branch>...HEAD` holds only that unit. No
push, no PR, no Linear. Conventional commits, no `Co-Authored-By`.
