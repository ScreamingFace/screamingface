---
ticket: unfiled   # set to OME-N at PR-open (bug, no parent epic: owner decision 2026-11-19)
---

# Plan: Colab analytics, finish browser round trips inside the cell

Spec: `docs/spec/2026-11-19-colab-analytics-in-cell.md` (D1–D3 approved by Filip on 2026-11-19,
as recommended). Ledger: `docs/work/2026-11-19-colab-analytics-status.md`. One unit, one PR,
`packages/screamingface` only.

## Steps (TDD, new tests only)

1. **D3, lost reply is a timeout.** New test: a fake `google.colab.output` module whose
   `eval_js` returns `None` makes `colab.exchange()` raise `TimeoutError`; through
   `prompt.before_evaluation()` status shows `setup_timeout` at stage `state`. Then in
   `exchange()`: raise `TimeoutError` when `eval_js` returns `None`.
2. **D1, setup settles at the sync entry points.** New `prompt.offer_and_settle()`:
   `offer()` then `wait_for_setup()` (already bounded to `BRIDGE_TIMEOUT`, already safe).
   Call it from the import hook (`screamingface/__init__.py`) and the two `connect()` panel
   paths (`client.py`, `_default_client.py`). `prompt.offer()` itself does not wait.
   WHY not inside `offer()`: `test_default_setup_timeout_invalidates_late_reply` pins that
   `offer()` returns before setup finishes, and `before_evaluation_async()` calls `offer()` on
   the event loop. New tests: with a fake browser that answers only while a "cell" flag is set
   and the flag cleared as soon as the triggering call returns, `offer_and_settle()` ends
   `accepted`; plain `offer()` under the same fake ends `unknown` (documents the bug); a
   never-answering browser bounds `offer_and_settle()` to `BRIDGE_TIMEOUT` plus tolerance;
   `DO_NOT_TRACK` makes it return at once with no exchange.
3. **D2, flush the terminal event.** `ColabBridge.flush(timeout)`: wait until every queued
   command has been dispatched (an in-flight counter under the existing condition), at most
   `timeout`. `tracking`: after a non-cancelled `_finish` in Colab, flush with
   `BRIDGE_TIMEOUT` (sync wrapper directly; async wrapper via `asyncio.to_thread` so the loop
   is not blocked). No flush for `cancelled`, outside Colab, or when no event was emitted.
   New tests: with the cell-flag fake cleared when the tracked call returns,
   `evaluation_finished` is acknowledged and status stays `accepted` (sync and async);
   a cancelled evaluation returns without waiting; a never-answering browser bounds the
   flush.
4. **Gates:** `uv run .claude/scripts/run_gates.py screamingface`. Any prior test that fails
   is a STOP (ask), never an edit.
   **Revised after the Colab check:** waiting inside `import screamingface` deadlocked on the
   package import lock, so the import hook uses `prompt.offer_at_import()`: `offer()` plus a
   one-shot IPython `post_run_cell` callback that calls `offer_and_settle()`. The connect
   panels keep the direct `offer_and_settle()`.
5. **Manual check** in a fresh Colab runtime with the built wheel (spec, Verification), then
   PR, bug filed in Triage with Irina and Kevin tagged, mirror in `docs/tasks/`.

## Risks

- Import of `screamingface` in Colab now waits for setup once per runtime (about 1–2 s healthy,
  5 s worst case). Approved as D1.
- Slower test runs where fake browsers block: bounded by `BRIDGE_TIMEOUT` per flush.
