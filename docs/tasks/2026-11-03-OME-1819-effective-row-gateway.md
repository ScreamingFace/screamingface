---
id: OME-1819
linear_url: https://linear.app/openmined/issue/OME-1819/mark-the-connection-chat-uses-in-the-gateway-connection-listing-l7a
status: done
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-03
closed: 2026-11-04
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
- 2026-11-04: the spec and plan squash-merged to `main` as `10de727e8` (PR #1658), then the code
  as `6e998fa4d` (PR #1660). Closed Done in Linear the same day with the close comment.
