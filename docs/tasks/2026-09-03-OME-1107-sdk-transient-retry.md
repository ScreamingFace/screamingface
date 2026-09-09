---
id: OME-1107
linear_url: https://linear.app/openmined/issue/OME-1107/retry-replay-safe-sdk-requests-on-transient-edge-failures
status: in_progress
type: null
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-03
closed:
---

# Retry replay-safe SDK requests on transient edge failures

A single Cloudflare **520** on one `POST /token` ended an `sf.evaluate` of 8 candidates — after
7 had already completed **100/100 cases at 100% cache hit**. The origin was healthy throughout:
nginx logged 14 `/token` requests, all 200, including 3 seconds either side of the failure. The
blip lived above the origin, in a flapping tunnel connection, and is environmental.

This unit is about why one blip was fatal:

1. **Nothing retried a request the SDK had itself declared replay-safe.** `/token` is sent with
   `extensions={_REPLAY_SAFE: True}` and was never replayed.
2. **The error pasted the raw body** — only `problem+json` was parsed, so ~7KB of Cloudflare
   markup reached the user with the status code buried inside it.

Retry is gated on the EXISTING `_REPLAY_SAFE` marker, never on the HTTP method. That marker is
already default-deny precisely because `GET /?q=` starts billable work despite being a GET — so
the one dangerous call is excluded by construction rather than by a rule someone must remember.

**Explicitly NOT fixed here:** the in-flight reservation leak and the all-or-nothing evaluation
semantics. Run start is deliberately not replay-safe, so this retry does not — and must not —
cover a refused run start.
