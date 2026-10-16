---
id: OME-1640
linear_url: https://linear.app/openmined/issue/OME-1640/aigateway-let-a-native-connection-repair-a-migrated-pairs-credential
status: in_progress
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-16
closed:
---

# aigateway: let a native connection repair a migrated pair's credential (Stage E, E1b)

Before the Profile routes retire (E3), the native Connection API repairs and switches a migrated
pair's effective credential the way the Profile facade did, using only the pair marker and the
Connection rows (spec R6). A native OAuth flow or API-key create replaces the effective row when
it is unusable, when the write names no label (the pair's main connection, keeping its real
label), or when it names that row's own label; the switch is fenced by the marker generation. A
sign-in into the identity of another row of the pair revokes that row with the old effective one,
and the fresh tokens land on the new row. No repair branch touches the Profile document; no
route, OpenAPI or `reauth_url` change. Part of OME-1209. Ledger:
`../work/2026-10-15-e1b-native-oauth-reauth.md`.
