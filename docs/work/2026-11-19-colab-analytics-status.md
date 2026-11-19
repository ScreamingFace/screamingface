---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-11-19
finished: 2026-11-19
---

# colab-analytics-status — Colab analytics status reports "unknown" although delivery works

## Intent

On SDK 0.1.14 in Colab, default analytics works end to end (consent cookie, browser ID and
events reach PostHog), yet `sf.analytics.status()` reports `choice: unknown`, `enabled: False`
and `*_invalid_response` errors. Users and support therefore see analytics as off, and the
SDK keeps re-running setup. Make the Colab bridge finish its browser round trips while the
triggering cell is still running, and report a lost reply as a timeout. Follow-up to OME-1768
(default-on analytics), found during its release smoke check on 2026-11-19.

## Root cause (reproduced 2026-11-19, fresh Colab runtime, SDK 0.1.14)

A Colab `eval_js` call made from the SDK's background worker only gets a reply while the cell
that started the work is still executing. After the cell ends, Colab's
`_message.read_reply_from_input` waits out the timeout and returns `None` (it does not raise).
The SDK then:

1. labels the `None` as `invalid_response` (`ColabBridge._exchange`), and
2. by design treats an unacknowledged event upload as an uncertain consent period and resets
   consent to unknown (`_apply`; pinned by `test_bad_delivery_acknowledgement_cannot_claim_success`).

Evidence, from a trace of every frontend request and stdin reply (`.docs/colab_trace.py`,
gitignored):

| Case | Cell executing when sent? | Reply |
|---|---|---|
| Setup at import: `state` | yes | 1.2 s |
| Setup at import: `id`, after the import cell ended | no | none, `None` after 5 s |
| Setup re-run inside a busy cell: `state`, `id` | yes | both, status `accepted` |
| `evaluation_started` / `evaluation_finished` uploads emitted inside `sf.evaluate` | yes | both |
| Delayed `state` after the cell ended, editor idle | no | none |
| Delayed `state` after the cell ended, autocomplete during the wait | no | none |
| Delayed `state` after the cell ended, request pinned to its own cell's parent header | no | none |

The last row rules out the parent header as the cause. Main-thread and in-cell calls with the
same code all succeed. Not individually traced: in the first (untraced) run the browser carried
out `enroll`/`id` minutes later during later cells, so a late call can still change browser
state while the kernel has already given up. The existing late-reply invariants already keep
that from enabling tracking.

## Planned changes

- `packages/screamingface/src/screamingface/_analytics/colab.py`
  - `exchange()`: a `None` result from `eval_js` raises `TimeoutError` (reported as
    `timeout`), instead of reaching the reply validator as a non-dict.
  - A bounded wait so Colab setup started by `offer()` finishes inside the triggering cell.
  - A bounded flush of the terminal event upload before a tracked operation returns.
- `packages/screamingface/src/screamingface/_analytics/prompt.py` and/or `tracking.py`: call
  sites for the two bounded waits (exact placement in the plan).
- New tests only (see Test plan). No prior test is edited.

## Test plan

- `exchange()` with a fake `google.colab.output` whose `eval_js` returns `None` raises
  `TimeoutError`; through the bridge this surfaces as `setup_timeout` at the failing stage.
- A fake Colab that only answers while a "cell" flag is set: setup triggered by `offer()`
  completes as `accepted` before `offer()` returns; with the flag cleared immediately after
  `offer()` (today's behaviour) the old code fails and the new code still succeeds.
- Terminal event: with the same fake, `evaluation_finished` is acknowledged before the tracked
  call returns, and status stays `accepted`.
- Bounds: a bridge that never answers delays `offer()` and the flush by at most
  `BRIDGE_TIMEOUT`; `DO_NOT_TRACK`, `disable()` and saved declines skip both waits.
- Cancellation: a `KeyboardInterrupt`/`CancelledError` evaluation does not wait for the flush.
- All prior analytics tests stay green and unmodified.

## Acceptance

- In a fresh Colab runtime with the built SDK: after `import screamingface` (or the first
  connect/evaluate), `sf.analytics.status()` reports `choice: accepted`, `enabled: True`, no
  `last_error`; after an evaluation it still does, and both events are in PostHog.
- A lost browser reply is reported as `*_timeout`, not `*_invalid_response`.
- `run_gates.py screamingface` green; no prior test edited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `_analytics/colab.py`: in-flight counter and `flush()`.
  - `_analytics/colab_transport.py` (new): the `eval_js` script template and `exchange()`,
    moved out of `colab.py` to stay under the 450-line limit. A `None` reply becomes the
    script's own timeout marker.
  - `_analytics/prompt.py`: `offer_and_settle()` and `offer_at_import()`.
  - `_analytics/tracking.py`: a bounded terminal-event flush in both wrappers, skipped on
    cancel.
  - `__init__.py`, `client.py`, `_default_client.py`: the call sites.
  - `tests/test_analytics_colab_in_cell.py` (new, 18 tests).
- **Commits:** `38e0215d1` ledger and spec · `f62a645ef` fix · `67a31db80` import settles
  after the importing cell.
- **Gates:** `run_gates.py screamingface` ALL GATES GREEN, run on the final code. The full
  suite (7,666 passed, 38 skipped, coverage 97.03%) was counted on `f62a645ef`. Append-only
  check green: no prior test edited.
- **Colab check (fresh runtime, branch build, 2026-11-19):**
  - `import screamingface` took 1.22 s. Status in the next cell: `accepted`, enabled, no
    error, 1 setup attempt.
  - After a fail-fast `sf.evaluate` (`PlanningError`, no model calls), status is still
    `accepted` with no error.
  - Not exercised in Colab: the first-time `enroll` path, because this browser already
    holds consent. The unit tests cover it.
- **Deviations:**
  - D3 is placed inside `exchange()` as the existing timeout marker, not as a raised
    `TimeoutError`. Raising would have broken the prior `test_analytics_endpoint.py`.
  - D1 at import uses an IPython `post_run_cell` callback. Waiting inside the import
    deadlocked on the import lock in real Colab, so the spec and plan were revised.
  - The transport moved to its own module for the file-size limit.
  - The new test file avoids re-importing fixtures under their own names, because the
    pre-commit ruff (0.14.0) flags that pattern. It also flags it in existing files, which
    were not touched.
