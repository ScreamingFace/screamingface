# OME-930 — Present the Cloudflare Access authorization URL in the panel

Linear: https://linear.app/openmined/issue/OME-930 · High · `py-screamingface`

## Problem

`sf.connect()` renders a **Log in** button for a hosted Engine. Clicking it does nothing
visible in Colab: the panel shows "Cancel" for the full 300s login timeout and then errors.
The user is never shown a URL, so there is no path from `sf.connect()` to an authenticated
session.

This blocks onboarding. `sf.connect()` is the entrypoint in six shipped notebooks including
`examples/00_quickstart.ipynb`, and is the only auth surface a non-power user meets.

## Why it fails — one fault

`_present_access_authorization` (`_access/contract.py:101`):

```python
def _present_access_authorization(authorization_url: str) -> None:
    print(f"Complete Cloudflare Access login in your browser:\n\n{authorization_url}\n")
    if _running_in_notebook():
        return
    webbrowser.open(authorization_url, new=2)
```

**The URL is printed where nobody can see it.** Login runs on the
`screamingface-access-login` worker thread, started from an ipywidgets button callback.
That output does not reach the cell in Colab, so the URL is generated correctly and
discarded. There is no other channel to the user.

### CORRECTION — there is no Colab-detection fault

An earlier revision of this spec (and of the Linear issue) claimed a second fault: that
`_running_in_notebook()` fails to recognise Colab and therefore calls `webbrowser.open` on
the Colab VM. **That was wrong.** `running_in_notebook()`
(`src/screamingface/_environment.py`) walks the **MRO**, and already handles this
deliberately:

```python
# WHY inspect the MRO: hosted notebooks such as Colab and Databricks subclass the
# ipykernel shell from their own modules, so the concrete class name alone lies.
return any(cls.__module__.startswith("ipykernel") for cls in type(shell).__mro__)
```

Colab's shell subclasses `ipykernel.zmqshell.ZMQInteractiveShell`, so the MRO is
`['google.colab._shell', 'ipykernel.zmqshell', 'builtins']` and the function returns
`True`. No browser is opened on the notebook host today.

The bad evidence: `type(get_ipython()).__module__` returns `google.colab._shell`, which
shows only the **leaf** class and is fully consistent with the MRO containing ipykernel.
It was misread as confirming the fault. **No change to `_environment.py` is needed.**

## The constraint that decides the design

`webbrowser.open` opens a browser **on the machine running the code**. In local Jupyter
that is the user's laptop, so it works. In Colab the kernel is a VM in a Google datacenter:
no display, and not the user's screen. **There is no channel from that process to the
user's browser.** Same reason a webserver cannot open a tab on a visitor's machine.

So the only thing that can cross the gap is content rendered *in the user's browser* — i.e.
an anchor in the widget. Fixing the Colab detection alone does not make the button work; it
only stops a pointless call.

Note this also means Jupyter never auto-opened either: `_present_access_authorization`
returns before `webbrowser.open` whenever `_running_in_notebook()` is true. Notebooks have
only ever had the `print`.

## What already exists (and why this is small)

Two pieces of the answer are already in the codebase.

**1. The presenter seam.** `_CloudflareAccessAuth.__init__` already accepts an injected
presenter (`_access/auth.py:106`):

```python
browser_presenter: _BrowserPresenter | None = None,
...
self._present_browser = browser_presenter or _present_access_authorization
```

and calls it **before** the blocking poll (`auth.py:439`):

```python
authorization_url = _access_authorization_url(self._origin, audience, public_key)
...
self._present_browser(authorization_url)          # URL is known here
print("Waiting for Cloudflare Access login to complete...")
token = self._poll_transfer(...)                  # blocks from here
```

Only tests wire it today (`tests/test_authentication.py`). Production never does.
So the port exists and is unused — `_access` already defines the contract, and nothing in
it needs to import `_ui`.

**2. The rendering pattern.** Provider OAuth already solves the same problem by rendering a
real anchor into the widget (`_ui/connection_view.py:364-369`):

```python
f"href='{authorize_url}' target='_blank' rel='noopener noreferrer'>Authorize</a>"
```

That HTML renders in the user's browser, so the click opens a tab on their own machine. It
works identically in Colab, Jupyter and VS Code.

**Correction to the issue as originally filed:** it said this "changes the shape of the
login API, which is a public contract". It does not. `login()`'s signature is untouched;
the presenter is already a parameter. This is wiring, not a redesign.

## Design

Flow after the change — two clicks, matching provider OAuth:

```
sf.connect()
  → ScreamingFace Hosted Engine · login required   [Log in]

click Log in
  → ... · waiting   [Authorize ↗]  [Cancel]        (panel keeps polling)

click Authorize ↗
  → new tab in the user's own browser → Cloudflare login → close tab
  → panel flips itself: authenticated   [Log out]
```

The final transition already works — the panel polls and `_complete_login_access` renders
the result. Only the middle step is missing.

### Decision: two clicks, not one

**Chosen: two clicks** (Log in → Authorize).

| | |
|---|---|
| Two clicks | The URL is minted only when the user asks to log in. Consistent with the provider-OAuth flow users already meet. No wasted work. |
| One click | The Log in control would itself be the anchor, requiring an authorization URL to be minted at render time for *every* panel — including already-authenticated users who will never click it — and those URLs can expire while sitting unclicked. |

Two clicks is one more interaction in exchange for not generating a keypair and an
authorization URL on every render. Rejected one-click for that reason; revisit only if the
extra click proves to be a real drop-off.

### VERIFIED — anchor clicks work inside Colab's output iframe

Colab renders widget output in a **sandboxed iframe**. A sandbox without `allow-popups`
blocks `target="_blank"`, in which case the link renders but clicking it does nothing —
the same class of failure as the bug this issue fixes.

The provider-OAuth row already uses this pattern (`_ui/connection_view.py:364-369`).
**Confirmed by the owner in real Colab** — the rendered link opens a new tab as intended,
so the sandbox permits it and this design holds. Reproduction:

```python
from IPython.display import HTML
HTML('<a href="https://example.com" target="_blank" rel="noopener noreferrer">Authorize</a>')
```

**Mitigation, kept anyway:** render the authorization URL as
selectable text alongside the link. Then a blocked popup degrades to copy-paste rather than
a dead end — which still matters for users whose own browser blocks popups.

### Contract

- The panel supplies a `browser_presenter` that records the URL and re-renders, instead of
  letting `_access` fall back to the stdout presenter.
- `_state` carries the pending Access authorization URL, alongside the existing
  `flows` used by provider OAuth.
- The Access row renders an `Authorize ↗` anchor while a URL is pending, with the same
  `target="_blank" rel="noopener noreferrer"` treatment as the OAuth row, and keeps
  **Cancel** available.
- The URL is cleared when login completes, is cancelled, or errors.
- The URL is **also** rendered as selectable text, so a blocked popup degrades to
  copy-paste. See the unverified-assumption section above.
- **A terminal is unchanged:** `webbrowser.open` is correct there and must keep working.
- `_access` must not import `_ui` (hexagonal rule). The presenter is passed *in*.

### Out of scope

- Cloudflare authentication itself, token storage, the transfer protocol.
- Provider-connection contracts and the OAuth flow's own behaviour.
- The public shape of `login()` / `sf.connect()`.
- The remaining bare `print`s in the login path ("Waiting for…", "…complete.") — they are
  noise in a notebook, but harmless; note them, do not chase them here.

## Acceptance

1. Clicking **Log in** renders a clickable authorization link in the panel that opens in a
   new tab on the user's own machine, **and** shows the URL as selectable text beside it.
2. The authorization URL is never delivered *only* via `print` from a worker thread.
3. No browser is opened on the notebook host.
4. A terminal still opens a browser directly.
5. The link is cleared on completion, cancellation, and error.
6. Access login and provider OAuth present an authorization URL through the same mechanism.
7. `_access` does not import `_ui`.
8. The **panel** behaves identically in Colab, Jupyter and VS Code. Note this is not total
   uniformity: presenters are additive, so the pre-existing `print` still runs and may be
   visible in local Jupyter but not in Colab. That difference is pre-existing and out of
   scope; it is called out so nobody reads "identical" as stronger than it is.

## Open question for the owner

The `Authorize ↗` link's label and placement — whether it replaces the **Log in** button in
the controls column or appears in the status column as the OAuth row does. This is a
`screamingface-design` call; the OAuth row is the obvious precedent and is the default
unless told otherwise.
