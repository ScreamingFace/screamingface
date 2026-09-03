---
id: OME-918
linear_url: https://linear.app/openmined/issue/OME-918/litellm-197-resurrects-a-closed-http-client-invalidating-two-shutdown
status: Done
type: Task
priority: High
labels: [aigateway, agentic, autonomous]
created: 2026-08-20
closed: 2026-08-20
---

# litellm 1.97 resurrects a closed HTTP client, invalidating two shutdown tests

The second, independent breakage in Dependabot #640 — surfaced only once the tortoise-orm
Literal typing regression (`OME-912`) was cleared.

litellm 1.97 turned `AsyncHTTPHandler.client` into a self-healing property that rebuilds the
client whenever it finds the stored one closed. Shutdown itself is unaffected — `close()`
genuinely releases the pool — but both §9.12 tests re-read `handler.client` *after* close, and
that read is what resurrects an open client, so their assertion could never hold again.

Fixed by binding the client once and asserting on that object. The invariant is preserved,
not weakened. Verified passing under both litellm 1.95.0 and 1.97.0, which is what let it land
ahead of the bump.

Two prior tests were modified — a `sdlc-python` rule 5 Confidence-Gate decision, raised with
the owner before any edit and approved as "fix the tests only". Gates run with
`--skip-append-only`, the runner's documented path; every other gate normal.

Still open on the issue: whether to block the resurrection itself, since a post-shutdown
access can silently open a pool nothing will close.

Canonical artifacts:

- Ledger: `docs/work/2026-08-20-OME-918-litellm-client-resurrection.md`
- PR: #668 (merged)
