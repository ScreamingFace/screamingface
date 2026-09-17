---
id: OME-926
linear_url: https://linear.app/openmined/issue/OME-926/keep-sfconnect-from-getting-stuck-on-checking-when-a-notebook-event
status: In Review
priority: High
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-21
closed: 2026-08-21
---

# Keep sf.connect() from getting stuck on "checking" when a notebook event loop changes

In Google Colab the documented no-argument `sf.connect()` can sit forever on
"ScreamingFace Hosted Engine · checking". The same Cloudflare Access discovery completes in
~0.2s in standard Jupyter against the same healthy hosted Engine.

Root cause, confirmed on the issue with a deterministic harness
(`worker_finished=True, captured_loop_closed=True, access_check_pending=True`):
`ConnectionPanel.widget()` caches the asyncio loop live at render time, then posts the
discovery result back with `loop.call_soon_threadsafe(...)` from a daemon thread. When the
notebook host has closed or replaced that loop, the call raises `RuntimeError`, which is
swallowed with a bare `return` — the completion never lands and `access_check_pending`
stays `True`. `access_status()` then reports `checking` forever, and the "Checking…" button
is rendered disabled, so the user has no way out.

The same "the captured loop is still alive" assumption is repeated in login completion and
the cross-panel auth broadcast, which is why the fix is one shared completion dispatcher
rather than three patches. Colab churns its event loop where Jupyter does not; the fix
removes the dependency on loop identity instead of branching on the host.

Canonical artifacts:

- Ledger: `docs/work/2026-08-21-OME-926-connection-panel-completion-dispatch.md`
- PR: #680 (merged as `7a2f7e48`)

Verified in Colab by the owner: the panel left "checking" and reached "login required",
which also retired the open risk that an inline completion might not repaint from a worker
thread. Two changes rode along with owner approval — an unrelated `_runtime/server.py`
annotation, and a guard so an `async def` Access probe is never read as a boolean.

Follow-up `OME-930` covers the **Log in** button, which is still dead in Colab: this issue
got the panel *to* a working button, not through it.
