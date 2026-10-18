---
id: OME-1650
linear_url: https://linear.app/openmined/issue/OME-1650/serve-anonymous-score-reads-outside-the-cloudflare-access-path-so-the
status: in_review
type: bug
priority: 2
labels: [bug, scoreboard, agentic, autonomous]
created: 2026-10-18
closed:
---

# OME-1650 — Serve anonymous score reads outside the Cloudflare Access path so the spec page shows the url4

Production Cloudflare Access gates every `/v1/scores` subpath and method. The public read
`GET /v1/scores/{id}` got a 302 for anonymous visitors, so the portal spec page silently hid the
copy-url4 button, paper link, metadata note and reproduction count. Fix: an anonymous alias
`GET /v1/public/scores/{id}` that shares `_read_score` and never reads identity; the portal calls
it. Related: `OME-1649`.

Ledger: ../work/2026-10-18-fix-public-score-read-access-gate.md
