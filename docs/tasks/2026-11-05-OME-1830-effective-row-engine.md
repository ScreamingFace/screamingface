---
id: OME-1830
linear_url: https://linear.app/openmined/issue/OME-1830/manage-the-connection-chat-uses-in-the-local-engine-l7b
status: done
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1138
created: 2026-11-05
closed: 2026-11-05
---

# Manage the Connection chat uses in the Local Engine (L7b)

The Local Engine selects the Connection chat uses, the row `GET /v1/oauth/connections` marks
`effective` (L7a), instead of the row labelled `screamingface`, and takes every Local status from
`GET /v1/provider-access`. `connect`, `start_oauth` and `disconnect` write by the spec's create
and repair table; every stale-row repair `DELETE` carries the status its listing showed
(`?expected_status=`, L7c), so a sign-in or key fix that lands meanwhile is never deleted.
Against a gateway that predates the `effective` field the Engine falls back to the label rule for
one release; its removal is `OME-1832`. Spec `docs/spec/2026-10-29-local-engine-effective-row.md`
§3-§5, plan `docs/plan/2026-10-29-local-engine-effective-row.md` §3, ledger
`docs/work/2026-11-04-effective-row-engine.md`.

- 2026-11-05: filed after L7c (`OME-1824`) merged; the PR opened.
- 2026-11-05: squash-merged to `main` as `529bdb7f9` (PR #1684). Closed Done in Linear the same
  day with the close comment.
