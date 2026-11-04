---
id: OME-1819
linear_url: https://linear.app/openmined/issue/OME-1819/mark-the-connection-chat-uses-in-the-gateway-connection-listing-l7a
status: in_progress
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-03
closed:
---

# Mark the Connection chat uses in the gateway Connection listing (L7a)

`GET /v1/oauth/connections` marks each row with a required, read-only `effective: bool`, true on
the row the default chat resolve serves and at most one per provider, so the Local Engine can
manage the Connection chat uses instead of the one labelled `screamingface`. One pure core rule
decides the row, and provider availability is re-expressed on it. Only a registered provider the
caller may view has an effective row; the marker and Connection reads are fenced by the pair
generations; a labelled create replaces an `expired` effective row. Spec
`docs/spec/2026-10-29-local-engine-effective-row.md` §2, plan
`docs/plan/2026-10-29-local-engine-effective-row.md` §2, ledger
`docs/work/2026-11-03-effective-row-gateway.md`.

- 2026-11-03: filed; the spec and plan PR and the code PR opened.
