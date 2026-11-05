---
id: OME-1831
linear_url: https://linear.app/openmined/issue/OME-1831/catch-the-admin-ui-up-with-the-gateway-l9
status: in_review
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-05
closed:
---

# Catch the Admin UI up with the gateway (L9)

The Admin UI's `schema.d.ts`, last regenerated at E3, is regenerated from the gateway's current
OpenAPI after L7c merged: the `effective` flag on the Connection listing (L7a),
`/v1/cache/entries`, the classification routes and the conditional delete's `expected_status`
(L7c), all additive. The UI drops its mapping of `credential_write_conflict`, retired in E5a, and
the brand README names the Connection action instead of "delete profile";
`profile_index_conflict` stays. Spec `docs/spec/2026-10-29-ome-1138-closeout.md` §4.9, plan
`docs/plan/2026-10-29-ome-1138-closeout.md` L9, ledger
`docs/work/2026-11-04-ui-schema-effective.md`.

- 2026-11-05: filed after L7c (`OME-1824`) merged; the PR opened.
