---
id: OME-1824
linear_url: https://linear.app/openmined/issue/OME-1824/let-a-connection-delete-require-the-rows-status-l7c
status: done
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-04
closed: 2026-11-05
---

# Let a Connection delete require the row's status (L7c)

`DELETE /v1/oauth/connections/{id}` takes an optional `?expected_status=pending|error`. With it,
the gateway re-checks the row inside the delete's own transaction, after its pair claim, and
refuses with 409 `connection_conflict` when the row has become the pair's effective row or no
longer has the expected status; the claim and every write roll back. Without the parameter the
delete is unchanged; any other value is a 422. This closes the race in which a Local Engine
stale-row repair deleted a row that an OAuth callback or an API-key write activated after the
listing. L7b waits on this leaf. Spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2a,
plan `docs/plan/2026-10-29-local-engine-effective-row.md` §3a, ledger
`docs/work/2026-11-04-stale-row-conditional-delete.md`.

- 2026-11-04: filed; the PR opened.
- 2026-11-05: squash-merged to `main` as `24d979a5e` (PR #1678). Closed Done in Linear the same
  day with the close comment.
