---
ticket: OME-926
stack: screamingface
status: done
started: 2026-08-21
finished: 2026-08-21
---

# OME-926 — one completion dispatcher for ConnectionPanel background work

## Intent

`sf.connect()` in Colab can remain forever on "checking". `ConnectionPanel` caches the
asyncio loop live at `widget()` time and posts every background completion back to *that*
loop via `call_soon_threadsafe`; when the notebook host has closed or replaced it, the call
raises `RuntimeError` which is swallowed with a bare `return`, so `access_check_pending`
never clears. Replace loop-identity dependence with one dispatcher that always runs the
completion, so Colab and Jupyter expose the same user-visible transitions.

FEATURE: hosted-Engine connection panel (`sf.connect()`).
STORY: as a Colab user, I run `sf.connect()` and reach Log in / provider rows / a readable
error — never a permanent "checking".

## Planned changes

- `packages/screamingface/src/screamingface/_ui/connections.py`
  - new `_dispatch(callback, *args)` helper: live loop resolved **at post time** →
    else cached `self._loop` if open → else run inline on the calling thread.
    INVARIANT: every path ends with the completion actually running.
  - route `_start_access_check_thread` (:309-336), `_start_login_thread` (:354-377) and
    `_auth_state_changed` (:395-404) through it; audit `_start_oauth` (:226-236) and keep
    its behaviour.
  - drop the silent `weakref` completion drop (:323-325).
  - `_repr_html_` (:146-152) must not render a stuck `checking` — it never starts the probe.
- `packages/screamingface/src/screamingface/_ui/connection_view.py` — stop rendering the
  "Checking…" button `disabled = True` (:242-245), so a hung probe stays recoverable.
- `packages/screamingface/tests/test_connection_panel.py` — tests (append-only).

Out of scope per the issue: Cloudflare auth, provider-connection contracts, other widgets.
`sf.connect()` stays non-blocking. No schema/model change, so S1 does not apply.

## Test plan

RED first, reusing `_panel`/`_text`/`_wait_for_button`/`_buttons` (:66-150) and
`_SharedAuthClient` (:110-149); styled after
`test_unexpected_login_failure_does_not_leave_panel_waiting` (:816-834). No prior test is
modified.

- **Regression guard:** render the real controller, close/replace the rendering loop before
  Access discovery completes, assert the panel leaves "checking".
- Access-required / unprotected-Engine / discovery-**error** each reach the right terminal
  state (the error path is currently untested).
- Login completion cannot remain on "Cancel" solely because the rendering loop changed.
- Module-level `sf.connect()` entrypoint (`_default_client.py:121-171`), not just the
  internal helper — explicitly required by the issue's acceptance.
- `_repr_html_` while `access_check_pending` does not render a stuck `checking`.
- Existing Jupyter connection + OAuth tests stay green and unmodified.

Baseline before this unit: `Checking…`, `checking`, `access_check_pending`,
`_start_access_check`, `_complete_access_check` appear **nowhere** in `tests/`.

## Acceptance

- The regression guard fails before the fix and passes after.
- All six issue acceptance bullets covered by a test.
- `uv run .claude/scripts/run_gates.py screamingface` green, including
  `--cov-fail-under=95`, the notebook determinism check, and the distribution check.

## Outcome

- **Actual files:**
  - NEW `src/screamingface/_ui/loop_dispatch.py` (80) — `_CompletionDispatcher`. Planned as
    an inline helper; extracted on owner approval because inlining pushed
    `connections.py` to 485 lines against the loop's ≤450 rule (already 454 on
    `origin/main`). Now 440.
  - `src/screamingface/_ui/connections.py` — three call sites routed through the
    dispatcher; both `except RuntimeError: return` swallows deleted; the dead `loop`
    parameter dropped from both thread starters; `_start_access_check` re-renders after
    marking the probe started.
  - `src/screamingface/_ui/connection_state.py` — `checking` requires
    `access_check_pending AND access_check_started`; hosts `_sync_access_probe`.
  - `tests/test_connection_panel.py` — 9 tests added (+1 prior test retargeted).
  - `src/screamingface/_runtime/server.py` — unplanned, owner-approved: see Deviations.

- **Commits:** `6f8540ac` server.py typing · `47d260a7` completion dispatcher ·
  `f6536f30` async-probe guard. PR #680.

- **Gates:** `run_gates.py screamingface --skip-append-only` — ALL GATES GREEN.
  1018 passed, 1 skipped; coverage ≥95% (gate 95%).

- **VERIFIED IN COLAB.** The owner ran the branch in Google Colab: the panel left
  "checking" and reached "login required" with a Log in button. This also retires the
  open risk that the inline-completion path might not repaint from a worker thread — it
  does.

- **Deviations:**
  1. **Dispatcher extracted to its own module** rather than inlined — owner-approved, to
     satisfy the ≤450-line rule. Gives the issue's "one completion-dispatch mechanism" a
     named home.
  2. **One prior test modified** — `panel._loop = stale_loop` →
     `panel._dispatcher.adopt(stale_loop)` in the OAuth live-loop test. Injection handle
     only; scenario and every assertion unchanged. Raised as a rule-5 Confidence-Gate
     decision and approved before editing. Gates therefore run `--skip-append-only`.
  3. **`_runtime/server.py` typed `app: Any`** — unrelated to OME-926, owner-approved.
     **Correction to an earlier claim in this ledger:** this was first justified as
     needed to make the local gates pass. That was wrong. The pyright error appeared only
     in a *stale shared-checkout venv* that had uvicorn installed from an earlier
     `--extra runtime` run; a clean venv (and CI, which installs only `--extra notebook`)
     never saw it. The annotation is genuinely wrong on its own merits — `object`
     satisfies none of `uvicorn.Config`'s `app` types — so the fix stands, but it was
     never gate-blocking. The commit message was rewritten to say so.
  4. **Retry affordance NOT implemented.** The plan floated making the disabled
     "Checking…" button clickable. Dropped: the issue's acceptance covers completions that
     have *finished*, which the dispatcher fully satisfies. A hung probe is a different
     defect and a live button needs retry machinery nothing yet demands (YAGNI).
  5. **`weakref` completion drop left alone.** The plan listed removing it; on reading, a
     GC'd or `_closed` panel has nothing to render, so returning there is correct. Only
     the `RuntimeError` path was the bug.
  6. **Async-probe guard bundled into this unit** rather than filed separately —
     owner-approved. `AsyncClient._access_required` is `async def` while
     `_start_access_check` checked only `callable(...)`, so the coroutine read truthy ⇒
     "access required" for every Engine, never awaited. `_sync_access_probe` now also
     gates on `iscoroutinefunction`, and both the initial state and the check resolve
     through it so they cannot disagree. Unreachable today (`ConnectionPanel` is built
     only from the sync `Client`).

- **Process error, recorded:** several `git stash push/pop` cycles were used to compare
  against `origin/main`. Stashes are shared across worktrees, and one `pop` applied an
  unrelated pre-existing stash (`codex-preserve-before-main-pull-2026-08-20`) into this
  worktree, leaving conflict markers in `client.py` and `tests/test_leaderboards.py`.
  Recovered with no loss: that stash was never dropped (a conflicted apply preserves it)
  and remains at `stash@{0}`; this branch's commits were already on `origin`. **Do not use
  bare `git stash` to diff against a base in this repo — use `git worktree` or
  `git show`/`git diff <ref>` instead.**

- **Discovered, NOT in scope — needs its own issue:** clicking **Log in** in Colab opens
  nothing. `_present_access_authorization` (`_access/contract.py:101`) `print()`s the
  authorization URL — from a worker thread inside a widget callback, so it is invisible in
  Colab — and then calls `webbrowser.open` only when `_running_in_notebook()` is False.
  That check requires the shell class module to start with `ipykernel`
  (`_access/contract.py:180-188`), but Colab's is `google.colab._shell`, so Colab tries to
  open a browser **on the Colab VM**. The real fix is a presenter seam so the panel renders
  the URL as a link rather than writing it to stdout. Workaround: call `client.login()`
  directly in a cell.

- **Latent, unfixed:** none remaining from the plan — the `AsyncClient` coroutine trap
  listed there was fixed here (Deviation 6).
