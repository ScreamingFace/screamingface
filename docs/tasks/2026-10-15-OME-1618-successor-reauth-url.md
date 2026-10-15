---
id: OME-1618
linear_url: https://linear.app/openmined/issue/OME-1618/aigateway-point-every-re-auth-url-at-the-connection-api-stage-e-e1
status: in_progress
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-15
closed:
---

# aigateway: point every re-auth URL at the Connection API (Stage E, E1)

Every refusal for an unusable stored credential carries a `reauth_url` on the Connection API
instead of a Profile route that Stage E retires: `/v1/oauth/connections` for OAuth targets and
resolve-time refusals, `/v1/oauth/connections/api-key` for an api-key target without a Connection,
and `/v1/oauth/connections/{id}/api-key` for an api-key target with one, including a migrated
pair. Prerequisite for retiring the Profile routes (E3). Part of OME-1209. Also lands the accepted
Stage E spec and plan. Ledger: `../work/2026-10-14-e1-successor-reauth-url.md`.
