---
id: OME-1195
linear_url: https://linear.app/openmined/issue/OME-1195
status: In Review
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
created: 2026-09-14
closed:
---

# Expose execution access in Gateway model discovery

Coordinating epic OME-1194: Gateway OME-1195 → existing Engine passthrough → Client OME-1042. Planned Engine unit OME-1196 canceled: the existing proxy already preserves unknown fields and response bytes.

Gateway implements `context.execution_access` in existing model-details discovery. Existing Engine code relays the field unchanged; Client rejects missing access before any Candidate dispatch. Only Gateway implementation is underway. See `docs/spec/2026-09-14-OME-1195-gateway-access.md`.

Review cleanup (2026-09-16): clarified identity exclusions, annotated configured, and added two access-only identity regressions. 13 focused tests and all Gateway gates pass, coverage 92.61%. Ledger: `docs/work/2026-09-16-OME-1195-identity-review.md`. PR remains in review.
