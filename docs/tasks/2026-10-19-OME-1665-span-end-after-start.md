---
id: OME-1665
linear_url: https://linear.app/openmined/issue/OME-1665/keep-a-spans-end-after-its-start-so-a-clock-step-cannot-abort-a
status: in_review
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic, autonomous]
parent:
created: 2026-10-19
closed:
---

# Keep a span's end after its start so a clock step cannot abort a finished run

The Engine runner read the wall clock at both ends of every wire span. A host clock step between
the two readings (lima-guestagent `SyncTime` on kind-on-Colima: about 211 ms back every 10 s)
published `end` before `start`, and the SDK aborted a run the Engine had finished. The Engine now
measures the duration with `time.monotonic()` from a wall-clock anchor, so `end >= start` always
holds. The SDK half is `OME-1666`. Follow-up: a run shorter than one clock step can still get
`completed_at` before `started_at` (`url4/streaming/lifecycle.py:88`).

Ledger: ../work/2026-10-19-sdk-span-time-order.md
