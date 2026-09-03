# OME-930 addendum — which channels actually update a widget in Colab

Measured directly in Google Colab against the live hosted Engine, 2026-08-21. Every row is
an observation, not an inference. This supersedes the delivery assumptions in
`2026-08-21-OME-930-access-authorization-link.md` and invalidates the "verified in Colab"
claim recorded for `OME-926`.

## The capability matrix

| Channel | Widget update reaches the browser? |
|---|---|
| Cell execution | **YES** |
| Button `on_click` handler | **YES** |
| Mid-handler, before the handler returns (`render` → `sleep` → `render`) | **YES — flushes immediately** |
| `loop.call_soon_threadsafe(...)` firing after the cell ended | **NO** |
| Direct widget mutation from a plain worker thread | **NO** |

Repro for the two failures, independent of this codebase: display a `VBox`, then replace its
`children` two seconds later from a daemon thread — either via `call_soon_threadsafe` or
directly. The cell reports a live running loop, the callback runs, the state changes, and the
browser keeps showing the original content.

## What this means

**There is no background update channel in Colab.** Visible work must complete inside a
synchronous execution context — a cell body or a click handler. Anything deferred past the
return of that context is lost, silently.

This is not a bug in the dispatcher added by `OME-926`. The dispatcher makes the *state*
correct and is right for local Jupyter. What it cannot do is repaint a hosted notebook,
because no mechanism can.

### Consequences for the shipped code

- `OME-926`'s acceptance criterion "Colab and Jupyter expose the same user-visible state
  transitions" is **not met**. Instrumented in Colab: `pending=False`, `started=True`,
  `thread=None`, `access_status() == "login_required"` — and the row still reads "checking".
  It appeared to pass earlier only because that session had no running loop, so the probe
  took the synchronous branch and resolved *before* the view existed.
- `OME-930` as first implemented cannot work either: the authorization URL is announced from
  the login worker thread through the same dispatcher.
- **Provider OAuth polling has the same defect** — `_poll_oauth` runs as a loop task, so a
  provider finishing its OAuth flow will not visibly update in Colab. Out of scope here;
  recorded so it is not rediscovered.

## Revised design

Two changes, both moving work into a channel that delivers.

### 1. The Access probe runs synchronously

Drop the worker thread for Access discovery and probe during `widget()`. The panel is then
constructed already showing its resolved state, so no repaint is needed anywhere.

This deletes the `checking` state rather than fixing it — which is the right outcome. As
noted during `OME-926`, `checking` only ever existed to avoid briefly flashing "Log in" on an
unprotected Engine; it is cosmetic, and it is the state that strands.

Trade-off accepted: `sf.connect()` blocks for the probe. Measured at ~0.2s against the live
hosted Engine. `OME-926`'s scope said "keep `sf.connect()` non-blocking" — a briefly blocking
panel that is correct beats a non-blocking one that never updates. The probe timeout should
be lowered from the 15s default so a dead Engine cannot hang the call.

### 2. The login flow lives inside one click handler

Because mid-handler renders flush immediately:

1. Log in clicked → mint the authorization URL **synchronously** → render the link. Appears
   at once.
2. Poll for the token **in the same handler**, so every render still reaches the browser.
3. Token arrives → render authenticated.

The user clicks Log in, clicks Authorize, and the panel updates itself. No "check now"
button, no instruction to re-run `sf.connect()`.

This requires splitting Access login into "begin, returning the URL" and "await completion",
which is the shape provider OAuth already has. A private `_begin_login()` keeps `login()`'s
public signature intact.

### OPEN — the polling budget

Unresolved: whether blocking a click handler freezes the Colab UI. It caps how long step 2
may poll. If the notebook stays usable, the handler can poll the full login window. If it
freezes, the poll must be short and the link must remain on screen so the user can finish
authorizing regardless. Do not implement step 2 without settling this.
