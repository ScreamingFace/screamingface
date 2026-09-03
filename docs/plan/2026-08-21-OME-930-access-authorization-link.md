# OME-930 — Implementation plan

Spec: `docs/spec/2026-08-21-OME-930-access-authorization-link.md`

## Shape of the change

A **subscription**, mirroring the `_subscribe_auth` pattern the panel already uses. The
panel registers a presenter; `_access` calls it when the authorization URL is minted;
the panel stores it and renders an anchor.

Registered presenters are **additive** — the existing default presenter still runs. This
means no current behaviour changes: a terminal still opens a browser, a notebook still gets
its `print`. We only add a channel that reaches the widget. (Acceptance #2 asks that the URL
is never delivered *only* via print, which additive satisfies.)

Chosen over the alternatives:

- **Not** a `login(presenter=…)` argument — that changes a public signature for a UI concern.
- **Not** constructor-only injection — `Client` is already built by the time the panel
  exists, and `browser_presenter` is a `__init__` parameter today.

## Steps

### 1. `_access/auth.py` — let presenters be registered after construction

`_CloudflareAccessAuth` currently binds one presenter in `__init__` (`:106,120`) and calls it
at `:439`. Add a subscribe seam alongside it:

- `subscribe_authorization(presenter: _BrowserPresenter) -> Callable[[], None]` — returns an
  unsubscribe, same contract as `_AuthListeners.subscribe`.
- At the `_present_browser(authorization_url)` call site (`:439`), also notify subscribers.
  Keep the constructor presenter as-is so tests and the terminal path are untouched.
- A raising subscriber must not break login — catch and carry on. INVARIANT: presentation
  never fails the login it is announcing.

Declare it on the `_ClientAuth` protocol (`_access/base.py`) so both auth implementations
satisfy it.

### 2. `client.py` — expose it the way `_subscribe_auth` is exposed

Add to `Client` (and `AsyncClient`, which has the same `_subscribe_auth` at `:469`):

```python
def _subscribe_authorization(self, presenter: Callable[[str], None]) -> Callable[[], None]:
    self._require_open()
    return self._engine_auth.subscribe_authorization(presenter)
```

Private, matching `_subscribe_auth` / `_access_required`. No public surface changes.

### 3. `_ui/connection_state.py` — carry the pending URL

Add `access_authorization_url: str | None = None` to `_ConnectionPanelState`. Sits next to
`flows`, which is the provider-OAuth equivalent.

### 4. `_ui/connections.py` — register, store, clear

- In `widget()`, next to the existing `_subscribe_auth` registration (which already guards
  on `callable(...)` and stores an unsubscribe), register the presenter the same way and
  keep its unsubscribe for `close()`.
- The presenter callback arrives **on the login worker thread**, so it must go through
  `self._dispatcher` — the mechanism OME-926 added. This is the first non-completion use of
  it and exactly what it is for.
- Clear `access_authorization_url` in `_complete_login_access` (all three outcomes:
  success, cancel, error) and in `_apply_auth_state` when not authenticating.

### 5. `_ui/connection_view.py` — render the anchor

While `access_authorization_url` is set and status is `waiting`, render an `Authorize ↗`
anchor beside **Cancel**, reusing the OAuth row's treatment (`:364-369`):
`target="_blank" rel="noopener noreferrer"`, and `escape(..., quote=True)` on the URL.

Reuse `_oauth_html` if it generalises cleanly; duplicate only if forcing reuse distorts it.

### ~~6. Colab detection~~ — DROPPED

The original plan added Colab to `_running_in_notebook()`. **Not needed:**
`running_in_notebook()` already walks the MRO and returns `True` in Colab, because Colab's
shell subclasses `ipykernel.zmqshell.ZMQInteractiveShell`. See the spec's correction
section. `_environment.py` is untouched.

## Test plan (RED first, append-only)

`tests/test_authentication.py` already drives presenters via `browser_presenter=` — reuse
that fixture style.

- **The regression guard:** panel + a client whose login blocks; assert an `Authorize` anchor
  carrying the authorization URL appears in the widget while login is pending.
- The presenter fires from a worker thread and still reaches the widget (via the dispatcher).
- URL cleared on success, on cancel, and on error — three cases.
- A presenter that raises does not fail the login.
- Terminal path unchanged: `webbrowser.open` still called when not in a notebook.
- The URL is HTML-escaped in the rendered anchor.
- `_access` does not import `_ui` — assert on the module's imports.

Gates: `uv run .claude/scripts/run_gates.py screamingface` (coverage floor 95%).

## Risks

- **`AsyncClient` parity.** It has its own `_engine_auth` and `_subscribe_auth`; add the
  method there too or the protocol lies. Not exercised by the panel today, but OME-926 just
  showed what an unexercised async path costs.
- **Anchor placement is a design call** — see the spec's open question. Defaulting to the
  OAuth row's precedent.
- ~~Colab detection~~ — dropped, see above. `running_in_notebook()` already handles it.
- **Anchor clicks in Colab: verified** by the owner. The selectable-URL fallback is kept
  for browser-level popup blocking, not for the sandbox.

## Owner-verify

Real Colab: run `sf.connect()`, click Log in, confirm an `Authorize` link appears, click it,
confirm the tab opens on your machine and the panel flips to authenticated. Also check both
light and dark themes.
