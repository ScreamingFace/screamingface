---
id: OME-1666
linear_url: https://linear.app/openmined/issue/OME-1666/clamp-an-inverted-span-in-the-sdk-instead-of-aborting-the-run
status: in_review
type: bug
priority: medium
labels: [bug, client-sf, agentic, autonomous]
parent: OME-1665
created: 2026-10-19
closed:
---

# Clamp an inverted span in the SDK instead of aborting the run

The SDK wire adapter (`_engine/contract.py` `_span`) clamps a span whose `end` precedes its
`start` to `end = start` and logs a warning, instead of raising and losing the run. It clamps and
never drops, so the span still counts toward cache hits and saved cost. The public `events.Span`
keeps rejecting `end < start`.

Ledger: ../work/2026-10-19-sdk-span-time-order.md
