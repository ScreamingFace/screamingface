---
id: OME-1522
linear_url: https://linear.app/openmined/issue/OME-1522/let-the-owner-run-the-paid-smoke-on-just-the-benchmarks-they-name
status: done
type: feature
priority: medium
labels: [client-sf, human, autonomous]
created: 2026-10-08
closed: 2026-10-08
---

# Let the owner run the paid smoke on just the Benchmarks they name

The paid smoke button gains an optional `benchmarks` field: comma-separated Benchmark ids
(e.g. `musique,inspect-gsm8k`). Filled in, the press runs exactly those and ignores `scope`;
a name the live Engine does not list fails the press before any paid call, listing the valid
ids. Empty keeps today's behaviour. The local twin takes the same as a second argument:
`just screamingface test-paid-benchmarks all musique`.

Ledger: `docs/work/2026-10-08-paid-smoke-named-benchmarks.md`.

- 2026-10-08: PR opened; the first named press is the owner's (ledger Owner-verify).
