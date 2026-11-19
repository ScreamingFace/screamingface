---
id: OME-1968
linear_url: https://linear.app/openmined/issue/OME-1968/show-the-right-reason-when-a-hosted-credit-lookup-or-a-management-key
status: Done
type: bug
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1294
created: 2026-11-18
closed: 2026-11-19
---

# Show the right reason when a hosted credit lookup or a management key fails

Follow-up to `OME-1935` (PR #1883), from its second independent review. A hosted panel
says "Lookup failed" when the credit request fails, not "Not available on hosted". A
rejected management key says "Management key rejected" on the account box, not "Key
rejected".

Spec: `docs/spec/2026-11-17-credits-repr.md`.
Ledger: `docs/work/2026-11-18-credit-reasons.md`.
Branch: `OME-1968-credit-reasons`.

Merged [PR #1942](https://github.com/ScreamingFace/screamingface/pull/1942) as `31c1158e8`.
Linear is Done.
