---
ticket: OME-1974
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

## Round 2 — review fixes for PR #1952 (2026-11-23)

sergio-bershadsky requested changes on PR #1952 (2 blockers). Both reproduced first, then fixed.

- **Blocker 1 — `tests/browser/analytics-colab.test.cjs` read the wrong module.** The bridge
  script moved to `colab_transport.py` in round 1, but the test still read `colab.py` and split
  on `_SCRIPT = r"""`, so `source` was `undefined` and all 12 tests failed at load
  (`TypeError: Cannot read properties of undefined (reading 'split')`). Fix: point the test at
  `colab_transport.py`. Verified: `node --test tests/browser/analytics-colab.test.cjs` — 12/12
  pass. Added `node --test tests/browser/analytics-colab.test.cjs` as its own CI step in
  `.github/workflows/screamingface-tests.yml` and as a gate in the `screamingface` card of
  `.claude/sdlc.local.md`.
  - **Not committed yet.** This edits an existing, already-committed test file, so the
    append-only gate requires a `.claude/test-change-approvals/OME-1974.json` manifest, and
    that manifest needs Filip's own direct sign-off (confirmed by the coordinating session —
    not something an agent writes on his behalf). The manifest entry this needs:
    `issue: "OME-1974"`, `branch: "OME-1974-colab-analytics-status"`,
    `files["packages/screamingface/tests/browser/analytics-colab.test.cjs"]`:
    `base_blob: ea3570c8356aa95a4e41504585aba2160723dbfc` (blob at the branch's current HEAD,
    `465ad4a4b`), `approved_blob: 4797c577fd92c628b49e705b94d87b3ea7eb871c` (blob with the
    one-line fix, verified locally). Format follows existing manifests, e.g.
    `.claude/test-change-approvals/OME-1918.json`.
  - **Gate gap found while checking this**: `.claude/scripts/approved_test_changes.py`'s
    `approved_unsupported_change` only recognizes `.ts`/`.tsx`, `.js` under `tests/`, and
    `.json`/`.url4` fixtures under `tests/` — not `.cjs`. Confirmed by running
    `append_only_check` directly against this diff: it fails with
    `M  tests/browser/analytics-colab.test.cjs  (existing test artifact is unsupported or
    unparseable)` even though the fix is correct and the browser test itself passes. A
    correctly-formed `OME-1974.json` manifest will not be enough on its own — the matcher
    also needs a `.cjs` branch (mirroring the existing `.js`-under-`tests/` case) before the
    gate can approve this file. Left unchanged pending Filip's decision; flagged in the
    handback report rather than edited unilaterally, since it's the fail-closed test-change
    gate itself.
- **Blocker 2 — no outer bound on the async delivery wait.** `tracking.py`'s `_settle_async`
  awaited `asyncio.to_thread(_settle, ...)` with no `asyncio.wait_for`, so concurrent calls
  queued on the asyncio default executor instead of each bounding independently at
  `BRIDGE_TIMEOUT` (reviewer measured 20 concurrent calls taking 20s). Fixed by wrapping the
  `to_thread` call in `asyncio.wait_for(..., timeout=BRIDGE_TIMEOUT)` and catching
  `TimeoutError` alongside the existing `RuntimeError`, mirroring
  `prompt.before_evaluation_async`. Added
  `test_concurrent_async_settles_bound_at_bridge_timeout_not_per_call` (new test, appended to
  `tests/test_analytics_colab_in_cell.py`): 4 concurrent `@tracked` async calls against a
  2-thread default executor and a bridge that never answers. Verified both directions —
  temporarily reverted the fix via a tagged `git stash` entry and confirmed the test fails at
  ~10.0 s (`ceil(4/2) * BRIDGE_TIMEOUT`, the old queueing behavior), then restored the fix and
  confirmed it passes at ~5.1 s. This file edit is a pure addition (new import, new test
  function appended at the end) so it is not blocked by the append-only gate.
- **Full suite**: `uv sync --extra notebook` then `uv run pytest tests/ -n auto --dist
  worksteal --cov=screamingface --cov-fail-under=95 -q` — see commit message / handback for the
  result recorded at commit time. `ruff check`, `ruff format --check`, `pyright` all clean.
- **Not done this round** (optional per the review, skipped to keep scope to the two
  blockers): the sync `_settle(record, ok=True)` success-path test, the `clear()`/`_done()`
  test, and the spec/plan wording fix for `exchange()`'s timeout marker vs. a raised
  `TimeoutError`.
- **Status**: blocker 2 fully fixed, tested, and ready to commit. Blocker 1's code fix is
  verified locally but NOT committed — waiting on Filip's sign-off on the
  `.claude/test-change-approvals/OME-1974.json` manifest (and, per the gate gap above,
  possibly a `.cjs` matcher change too) before it can pass CI's append-only check.
