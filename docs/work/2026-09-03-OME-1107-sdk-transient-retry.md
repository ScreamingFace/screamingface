---
ticket: OME-1107
stack: screamingface
status: in_progress
started: 2026-09-03
finished:
---

# OME-1107 — retry replay-safe SDK requests on transient edge failures

## Intent

A single Cloudflare 520 on one `POST /token` destroyed an `sf.evaluate` of 8 candidates, after
7 had already completed 100/100 cases at 100% cache hit. The origin was healthy throughout —
nginx logged 14 `/token` requests, all 200, including 3 seconds either side of the failure —
so the 520 came from a flapping tunnel connection above the origin. The blip was environmental
and is already resolved; this unit is about why one blip was fatal.

Two SDK defects turned it into total loss:

1. **No retry, despite the request declaring itself replay-safe.** `_mint_sync`/`_mint_async`
   send `/token` with `extensions={_REPLAY_SAFE: True}`, and nothing ever replays it.
2. **The error pastes the raw body.** `_raise_response` sets `detail = response.text.strip()`
   and parses only `application/problem+json`, so an HTML edge page lands verbatim in the
   exception — 7KB of Cloudflare markup hiding the one useful token, the status code.

## Design

**Gate retry on the EXISTING `_REPLAY_SAFE` extension, never on the HTTP method.** That flag is
already an explicit, default-deny property of the request (`_access/auth.py:568`), introduced
because `GET /?q=` starts a Run despite being a GET — "any generic layer that assumes GETs are
replayable can double-fire it". Replay-safety is a property of the REQUEST (does re-sending
duplicate a side effect), not of the failure mode, so the same flag answers both "safe to
re-send after Access re-auth" and "safe to re-send after a transient 5xx".

This makes the dangerous case safe by construction:

| call | `_REPLAY_SAFE` | retried |
|---|---|---|
| `POST /token` (mint) | True | yes — the call that failed |
| `DELETE /` (stop) | True | yes, idempotent |
| **`GET /?q=` (run start)** | **absent → False** | **never** |

Implemented as an httpx transport wrapper so the policy lives in ONE place rather than at each
call site, and cannot be forgotten by the next caller.

## Planned changes

- `packages/screamingface/src/screamingface/_core/retry.py` — NEW. Sync + async transport
  wrappers: retry only replay-safe requests, only on retryable status or transport error,
  bounded attempts, exponential backoff with jitter, honouring `Retry-After`.
- `packages/screamingface/src/screamingface/_engine/transport.py` — wire the wrappers into the
  two engine clients; cap and summarise non-`problem+json` bodies in `_raise_response`.
- `packages/screamingface/tests/test_transient_retry.py` — NEW file (tests are append-only).

## Test plan

- A replay-safe request meeting a retryable 5xx (520/502/503/504) is retried and succeeds when
  a later attempt does.
- A request WITHOUT `_REPLAY_SAFE` is **never** retried — the run-start invariant. Asserted
  directly, since violating it double-fires billable runs.
- A 4xx (400/401/404) is not retried.
- `Retry-After` is honoured when present, in both delta-seconds and HTTP-date form.
- The attempt budget is bounded — a permanently failing endpoint stops and surfaces the error.
- A transport-level connection error is retried, and the final failure still raises.
- An HTML error body yields a bounded message naming the status code, not the raw page.
- `problem+json` detail extraction is unchanged.

## Acceptance

- The mint path survives a single transient 520 without user-visible failure.
- Run start is provably never retried.
- `run_gates.py screamingface` green (coverage gate is 95% on this package).

## Outcome

- **Actual files:** as planned, plus the `docs/tasks/` mirror.
  - `src/screamingface/_core/retry.py` — NEW. `RetryingTransport` / `RetryingAsyncTransport`
    sharing one `_RetryPlan`, so the sync and async policies cannot drift.
  - `src/screamingface/_engine/transport.py` — both engine clients wired to the retrying
    transports; `_body_summary` replaces the raw-body error detail.
  - `tests/test_transient_retry.py` — NEW, 29 tests.
  - `docs/tasks/2026-09-03-OME-1107-sdk-transient-retry.md` — NEW mirror.
- **Commits:** `fix(screamingface): retry replay-safe requests on transient edge failures`
- **Gates:** `run_gates.py screamingface` — ALL GATES GREEN (append-only · ruff check · ruff
  format · pyright · pytest --cov ≥95 · notebooks · uv build · distribution).
  **The append-only check passed on its own — no `--skip-append-only`**, because this unit adds
  a new test file and touches no prior test.
- **Deviations:**
  1. **No new retry vocabulary was invented.** The plan considered a bespoke "retryable"
     notion; the implementation instead reuses `_REPLAY_SAFE`, which `_core/wire.py` already
     defines as default-deny and describes as costing "one extra round trip — never an extra
     paid Run". Replay safety is a property of the REQUEST, so one marker legitimately answers
     both "safe after an Access login" and "safe after a transient 5xx". This is why run start
     is excluded by construction.
  2. **500 is deliberately NOT retryable.** An application error is deterministic; repeating it
     wastes the caller's time and hides the defect. The retry set is the gateway/edge family
     plus 408/429/503.
  3. **`Retry-After` beyond a 30s cap stops rather than sleeping.** Obeying an hour-long value
     is indistinguishable from a hang; surfacing the response lets the caller decide.
  4. **Three gate iterations**, all in my own new code: import order, two functions exceeding
     the return-count limit (fixed by extracting `_http_date` and flattening `_body_summary`,
     not by suppressing), and one long line. A fourth red was environmental — the worktree
     lacked the optional `notebook` extra, so pyright could not resolve `ipywidgets` in files
     this unit never touched; `uv sync --all-extras` fixed it.

## Scope explicitly NOT covered

- **The in-flight reservation leak.** Run start is not replay-safe, so a refused `GET /?q=` is
  never retried here — correctly, since retrying it would double-fire billable Runs. That leak
  bit again on the same cluster ~25 minutes after this incident: the App still held 8
  reservations from the earlier evaluation, refusing 7 of 8 candidates with 503 against an idle
  pool, and the refused candidates hung rather than erroring because the reaper is disabled
  (`URL4_CLOUD_ORPHAN_GRACE_S=0`, which `app.py` honours silently).
- **All-or-nothing evaluation semantics** (`_evaluation/runner.py:382-389`).

Both remain open follow-ups and are the reason a single refusal still costs a whole evaluation.
