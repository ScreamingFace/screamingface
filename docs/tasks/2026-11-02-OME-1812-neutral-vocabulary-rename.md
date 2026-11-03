---
id: OME-1812
linear_url: https://linear.app/openmined/issue/OME-1812/name-credentials-and-connections-in-the-gateway-runtime-vocabulary-l5
status: in_progress
type: task
priority: low
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-02
---

# Name credentials and connections in the gateway runtime vocabulary (L5)

The gateway runtime names a credential's address `credential_name`, the pending OAuth entry's
label `fallback_label`, and the authorize module `connection_authorize`. Chat no longer threads
the always-`default` selector name, and the dispatch log lines drop the `profile=` field. The
model-admission reauth and pending refusals and the `ApiKeyStrategy` help text say
"connection"; the wire codes `profile_not_found` and `profile_pending_auth` stay. Migrations keep
their column names; the `X-AIGW-Gemini-Profile` and `X-AIGW-Antigravity-Profile` headers are
wire and stay. Spec `docs/spec/2026-10-29-ome-1138-closeout.md` §4.5, plan
`docs/plan/2026-10-29-ome-1138-closeout.md` section L5, ledger
`docs/work/2026-11-02-neutral-vocabulary-rename.md`.

- 2026-11-02: filed, implemented, PR opened.
