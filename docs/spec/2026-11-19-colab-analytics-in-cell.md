---
ticket: unfiled   # set to OME-N at PR-open
---

# Colab analytics: finish browser round trips inside the cell

Follow-up to OME-1768. Root cause and evidence: `docs/work/2026-11-19-colab-analytics-status.md`.

## Problem

In Colab, the SDK talks to the analytics service through the browser: the kernel sends a
script with `google.colab.output.eval_js` and waits for the reply. The SDK sends from a
background worker thread. A reply only comes back while the cell that started the work is
still executing. Two of the SDK's round trips regularly run after that cell has ended:

- setup started by `offer()` (on import, client creation or connect): the first step
  (`state`) usually answers, the next (`enroll` or `id`) is sent after the cell ended;
- the `evaluation_finished` upload when the worker sends it after the cell ended (seen after an
  interrupted evaluation).

Colab then returns `None` after the 5 s timeout. The SDK reports it as `invalid_response`, and
for an event upload it also resets consent to unknown (an intended invariant: an
unacknowledged upload is an uncertain consent period). Users see `enabled: False` and
`setup_invalid_response` although consent, the browser ID and events all reached PostHog.

## Behaviour after the change

1. **A lost reply is a timeout.** When `eval_js` returns `None`, `exchange()` raises
   `TimeoutError`. Status shows `setup_timeout` / `delivery_timeout` at the stage that was
   waiting. Replies that do arrive but are malformed are still `invalid_response`.
2. **Colab setup finishes inside the triggering cell.** `sf.connect()` / `Client.connect()`
   wait for the setup they started, at most `BRIDGE_TIMEOUT` (5 s). `import screamingface`
   cannot wait inside the import (the worker's own `screamingface` imports block on the package
   import lock, verified in Colab), so it registers a one-shot IPython `post_run_cell` callback
   that waits right after the importing cell's code, while Colab still treats the cell as
   running. A healthy browser answers in about 1–2 s. Afterwards `status()` reports `accepted`
   with no error. `prompt.offer()` itself stays non-blocking.
3. **The terminal event is flushed before the tracked call returns.** After a tracked operation
   emits its terminal event in Colab, the wrapper waits for the bridge to acknowledge it, at
   most `BRIDGE_TIMEOUT`. A cancelled operation (`KeyboardInterrupt`, `CancelledError`) does not
   wait; its terminal event is best-effort, and if it is lost the existing invariant applies
   (consent unknown until the next evaluation re-runs setup inside its cell).
4. **Unchanged:** explicit opt-outs (`DO_NOT_TRACK`, `disable()`, saved decline) skip setup and
   both waits; a late reply from an expired attempt can never enable tracking; an
   unacknowledged upload still resets consent; no event replay; no service change; non-Colab
   environments are untouched.

## Decisions for sign-off

| # | Decision | Recommended | Alternative |
|---|---|---|---|
| D1 | Make Colab setup started on import or connect finish inside that cell, up to 5 s | Yes: status is right from the first cell, and the notice keeps its earliest touchpoint | Start setup only at the first evaluation (no import delay; status reads `unknown` until then) |
| D2 | Flush the terminal event before a tracked call returns, up to 5 s, skipped on cancel | Yes | Leave delivery fully async (status can still flip to unknown after an evaluation) |
| D3 | Map a `None` reply to `timeout` inside the real `exchange()` | Yes | Map it in `ColabBridge._exchange`, which changes a pinned prior test (`test_safe_failure_details_clear_after_recovery`, `(None, "invalid_response")`) |

With the recommended options **no prior test changes**: prior tests replace `colab.exchange`
itself, so the `None` mapping inside the real function does not reach them, and the step
sequences they pin (`state` → `enroll` → `id`) stay as they are.

## Out of scope

- The 4-minute "Queued" hosted evaluation seen during the smoke check (separate, not analytics).
- OME-1793 (exposing more failure reasons).
- Making Colab's `eval_js` thread-safe or changing the analytics service.

## Verification

Unit tests with a fake Colab frontend that answers only while a "cell running" flag is set
(see the ledger's test plan), then a manual check in a fresh Colab runtime with the built
wheel: `status()` is `accepted` after import and after an evaluation, and PostHog shows the
evaluation's start and finish events.
