---
id: OME-1127
linear_url: https://linear.app/openmined/issue/OME-1127
status: In Progress
type: bug
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-07
closed:
---

# Model calls that die mid-evaluation must receive accurate failure classification

Distinguish interrupted delivery and transient provider failures from complete malformed gateway responses. Keep failures and incurred spend visible. Verify candidate COMMIT failures are attributed to the candidate stage.

See [work ledger](../work/2026-09-07-OME-1127-model-call-failures.md).

## Scope reconciliation — 2026-09-09

PR #846 merged (0829106b; final head 2f4885a3). Delivered: MedXpert input/order fix, candidate-stage attribution, model_empty_content for reasoning-only replies (still permanent), Engine lifecycle logs/heartbeats, and completed-Case reasoning retention.

Khoa's captured response establishes a blank-prompt/complete-reasoning-only failure, not a proven transport outage. Historical outage explanations are not confirmed for both original evaluations.

Remaining: real interrupted-delivery e2e tests; explicit policy for a complete empty 200; malformed-body and 429/5xx regression protection; report-level candidate/checker-stage tests; reconcile Engine versus Gateway logging ownership; coordinate privacy-safe failure diagnostics with OME-784. Keep In Progress. Linear contains the authoritative revised acceptance and preserved historical report.

## Classification implementation — 2026-09-09

Implemented zero-byte completed responses as retryable `aigateway_empty_response`, without additional immediate retries. Added 5 unit cases and 17 real-loopback integration cases through the final MedXpert report. Covers interrupted framing, both candidate turns, complete reasoning-only responses, HTML, 429/503, checker stage, recorded spend, and successful scoring. Broader diagnostics/logging ownership remains open; this change does not close the ticket.
