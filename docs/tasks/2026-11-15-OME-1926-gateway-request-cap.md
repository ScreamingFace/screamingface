---
id: OME-1926
linear_url: https://linear.app/openmined/issue/OME-1926/raise-the-aigateway-request-body-cap-to-12-mib-so-url4-attachments-fit
status: done
type: task
priority: 0
labels: [aigateway, agentic, autonomous]
created: 2026-11-15
closed: 2026-11-16
---

# Raise the AIGateway request-body cap to 12 MiB so url4 attachments fit

Mirror of OME-1926 (parent epic OME-1529).

**Problem.** url4 admits up to 8,000,000 attachment bytes (PR #1588), 10,666,668 bytes in base64.
The gateway's 8 MiB default body cap refused a legal 6.5 MB image with 413 `request_too_large`.

**Fix.** Default `max_request_bytes` = 12 MiB (12,582,912), 1,916,244 bytes left for prompt and
envelope; the frozen-copy entry cap follows (14,680,064). Owner decision (HupBaHa's review,
2026-11-13). Two prior tests that pinned 8 MiB changed, owner-approved 2026-11-15.

Ledger: `docs/work/2026-11-15-gateway-request-cap.md`.
