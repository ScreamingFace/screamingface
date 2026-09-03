---
id: OME-930
linear_url: https://linear.app/openmined/issue/OME-930/surface-the-cloudflare-access-authorization-url-in-the-connection
status: In Progress
priority: High
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-21
closed:
---

# Surface the Cloudflare Access authorization URL in the connection panel instead of stdout

Clicking **Log in** in Colab does nothing visible. The authorization URL is written to
stdout from a worker thread inside a widget callback (invisible in Colab), and
`_running_in_notebook()` does not recognise Colab — confirmed, its shell is
`google.colab._shell` — so the client also calls `webbrowser.open` on the Colab VM.

Blocks the primary onboarding path: `sf.connect()` is what six shipped notebooks call,
including the quickstart, and it is the only auth surface a normal user meets. `OME-926`
got the panel *to* a Log in button; this makes the button work.

Key finding: the presenter seam already exists. `_CloudflareAccessAuth.__init__` accepts
`browser_presenter` (`_access/auth.py:106,120`) and `_present_browser(url)` is called
*before* the blocking poll (`auth.py:439`), so the URL is available mid-login. Only tests
wire it today. No new abstraction and no change to `login()`'s signature are needed.

Canonical artifacts:

- Spec: `docs/spec/2026-08-21-OME-930-access-authorization-link.md`
- Plan: `docs/plan/2026-08-21-OME-930-access-authorization-link.md`
- Ledger: `docs/work/2026-08-21-OME-930-access-authorization-link.md`
- PR: (pending)
