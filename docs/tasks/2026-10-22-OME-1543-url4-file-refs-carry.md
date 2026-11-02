---
id: OME-1543
linear_url: https://linear.app/openmined/issue/OME-1543/carry-file-refs-through-url4-fan-out-reduce-and-iteration-intact
status: in_review
type: feature
priority: high
labels: [url4-sdk, agentic, autonomous]
created: 2026-10-22
closed:
---

# Carry file refs through url4 fan-out, reduce and iteration intact

A url4 run keeps one frozen `attachments[]` manifest (spec #1450 / `OME-1535`): opt-in attachment
sources (`;accept=` naming exactly one image/PDF type), literal URLs only, caps of 20 entries /
8,000,000 bytes, frozen before the first model call and carried unchanged through fan-out, reduce,
iteration and retries. `Url4Node` gains a guarded, binary-safe `fetch_bytes`; `url4 serve` serves
binary `[data]` files byte-exact in-process. Text sources keep today's semantics byte-for-byte.

Parent epic `OME-1529`. Depends on `OME-1539` (#1482) and `OME-1538` (#1478).
Ledger: `../work/2026-10-22-file-refs-carry.md`.
