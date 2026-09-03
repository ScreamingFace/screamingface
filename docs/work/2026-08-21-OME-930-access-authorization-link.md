---
ticket: OME-930
stack: screamingface
status: done
started: 2026-08-21
finished: 2026-08-21
---

# OME-930 — present the Access authorization URL in the panel

## Intent

Clicking **Log in** in Colab does nothing visible: the authorization URL is written to
stdout from a worker thread inside a widget callback, and `_running_in_notebook()` does not
recognise Colab so the client also opens a browser on the Colab VM. Give the panel the URL
so it can render a real anchor, which is the only thing that can reach the user's own
browser from a remote kernel.

FEATURE: hosted-Engine connection panel (`sf.connect()`) — Cloudflare Access login.
STORY: as a Colab user clicking Log in, I get a link I can click that opens Cloudflare
Access in my own browser, and the panel then shows me as authenticated.

Blocks onboarding: `sf.connect()` is the entrypoint in six shipped notebooks including the
quickstart, and the only auth surface a non-power user meets.

## Planned changes

Per `docs/plan/2026-08-21-OME-930-access-authorization-link.md`:

- `_access/auth.py` — `subscribe_authorization()` on `_CloudflareAccessAuth`; notify
  subscribers at the existing `_present_browser` call site (`:439`), additively, so the
  terminal and existing tests are untouched. A raising subscriber must not fail the login.
- `_access/base.py` — declare it on the `_ClientAuth` protocol.
- `client.py` — `_subscribe_authorization()` on `Client` **and** `AsyncClient`, mirroring
  `_subscribe_auth`. No public surface change; `login()`'s signature is untouched.
- `_ui/connection_state.py` — `access_authorization_url: str | None`.
- `_ui/connections.py` — register the presenter in `widget()`, route it through
  `self._dispatcher` (it arrives on the login worker thread), unsubscribe in `close()`,
  clear the URL on success/cancel/error.
- `_ui/connection_view.py` — render an `Authorize ↗` anchor beside Cancel, reusing the
  OAuth row's `target="_blank" rel="noopener noreferrer"` treatment.
- `_access/contract.py` — `_running_in_notebook()` also recognises `google.colab`.

No schema or model change, so S1 does not apply.

## Test plan

RED first, append-only. Reuse the `browser_presenter=` fixture style already in
`tests/test_authentication.py`.

- Anchor carrying the authorization URL appears in the widget while login is pending.
- The presenter fires from a worker thread and still reaches the widget.
- URL cleared on success, on cancel, and on error.
- A presenter that raises does not fail the login.
- `_running_in_notebook()` parametrized over `google.colab._shell`, `ipykernel.*`, neither.
- Terminal path unchanged — `webbrowser.open` still called outside a notebook.
- The URL is HTML-escaped in the anchor.
- `_access` does not import `_ui`.

## Acceptance

The spec's eight acceptance criteria, and
`uv run .claude/scripts/run_gates.py screamingface` green including the 95% coverage floor.

## Outcome

- **Actual files:**
  - `_access/auth.py` — `subscribe_authorization()` + `_announce_authorization()`, notified at
    the existing `_present_browser` call site. **Additive**: the constructor presenter still
    runs, so the terminal browser-open path and every existing test are untouched.
  - `_access/base.py` — declared on the `_ClientAuth` protocol.
  - `client.py` — `_subscribe_authorization()` on **both** `Client` and `AsyncClient`.
    `login()`'s signature untouched; no public surface change.
  - `_ui/connection_state.py` — `access_authorization_url: str | None`.
  - `_ui/connections.py` — subscribe in `widget()`, release in `close()`, route the
    announcement through `self._dispatcher` (it arrives on the login worker thread), clear
    on every login outcome and when the shared auth state stops authenticating.
  - `_ui/connection_view.py` — `_authorization_link()` renders the anchor plus the URL as
    text, reusing the OAuth row's `target="_blank" rel="noopener noreferrer"` treatment.
  - `tests/test_connection_panel.py` (+8), `tests/test_authentication.py` (+3).

- **Gates:** `run_gates.py screamingface` — ALL GATES GREEN, including the append-only check
  (no prior test was touched this time). 1027 passed, 1 skipped; coverage ≥95%.

- **Deviations:**
  1. **`_environment.py` untouched — planned step dropped.** The plan and the issue both
     claimed `_running_in_notebook()` fails to recognise Colab. **Wrong.**
     `running_in_notebook()` walks the MRO and already returns `True` there, because Colab's
     shell subclasses `ipykernel.zmqshell.ZMQInteractiveShell`; the function carries a
     comment saying exactly that. The bad evidence was
     `type(get_ipython()).__module__ == "google.colab._shell"`, which shows only the leaf
     class. Retracted in the spec and on the issue. No browser was ever being opened on the
     notebook host, so that acceptance criterion was void, not met.
  2. **Anchor-in-Colab verified** by the owner before implementation: an
     `<a target="_blank">` rendered via `IPython.display.HTML` does open a tab from inside
     Colab's sandboxed output iframe. This was the load-bearing assumption; had it failed,
     the whole design would have needed replacing. The selectable-URL fallback was kept
     anyway, now justified by browser-level popup blocking rather than the sandbox.
  3. **`connections.py` is 472 lines, over the ≤450 guideline.** No clean seam presents
     itself: the three new methods are controller glue over `_state` and `_dispatcher`, and
     `_authorization_announced`/`_apply_authorization_url` deliberately mirror the existing
     `_auth_state_changed`/`_apply_auth_state` pair. Extracting them would manufacture an
     abstraction to satisfy a line count. Noted for the reviewer rather than forced — see
     also `connection_view.py`, which was already 528 lines on `main` before this change.
  4. **The pre-existing `print`s in the login path are untouched** — the URL banner and the
     "Waiting for…" / "…complete." lines. Presenters being additive means a local Jupyter
     user may now see both a printed URL and the panel link. Redundant but harmless, and
     changing it would alter behaviour that currently works for terminal users.

- **Not verified by me:** the end-to-end Colab click-through. The anchor mechanism is
  owner-confirmed and the panel transitions are covered by tests, but nobody has yet run
  Log in → Authorize → authenticated against the live hosted Engine in Colab. See
  Owner-verify.
