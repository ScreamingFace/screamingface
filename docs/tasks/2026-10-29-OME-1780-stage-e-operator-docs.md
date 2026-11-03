---
id: OME-1780
linear_url: https://linear.app/openmined/issue/OME-1780/document-the-stage-e-rollback-floor-and-upgrade-path-for-operators
status: done
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
closed: 2026-11-02
---

# Document the Stage E rollback floor and upgrade path for operators

Close-out leaf L10 of the Stage E epic. `apps/aigateway/DEPLOYMENT.md` gains a Stage E section under
"Migrations": the rollback floor after the E5b purge (every image must include E4b `f7e54869b`), the
upgrade path for a Helm install that still holds Profile rows (an E5b-era image such as
`main-1ccf80a` runs `migrate_profiles` and then `purge_profile_history`, then an image built from E5c
`7cb093014` onward), and what the 410 `legacy_profile_api_retired` routes mean. Profile-era wording
is corrected in the chart README, the gateway README and `docs/diagrams/gateway-identity.md`, which
now also lists the credential-resolution refusals. Docs only. The L4c `0016` downgrade floor lands
with L4c.

After L4a merged (`e915d8037`, #1614) the branch was rebased onto it. `DEPLOYMENT.md` now states the
precondition for an image that includes L4a: count the `quarantined` and non-null `migration_note`
rows, settle them, and recount to 0. The pre-L4a `409 credential_pair_unresolved` sentence is gone
from `DEPLOYMENT.md` and `docs/diagrams/gateway-identity.md`.

After review (2026-11-02): the remediation runs with every pre-L4a gateway replica stopped and in
one bounded transaction, because an older gateway can write an observed `quarantined` back; spec
§4.2 gains the same amendment. `gateway-identity.md` and its flow diagram scope
`409 connection_ambiguous` to a pair without an effective reference.

#1612 merged on 2026-11-02 (`969d4e303`) with the first three commits only; the L4a precondition
and the review fixes land in a follow-up PR from branch `OME-1780-l4a-precondition-docs`.
That follow-up merged as `41017c289` (#1637). A second follow-up makes every `helm upgrade` in the
runbook keep the release's values; an upgrade given only `--set` flags renders from the chart
defaults.

Spec: `docs/spec/2026-10-29-ome-1138-closeout.md` §4.10. Plan:
`docs/plan/2026-10-29-ome-1138-closeout.md` §3 "L10". Ledger:
`docs/work/2026-10-29-stage-e-operator-docs.md`.

- 2026-11-02: merged in three PRs: `969d4e303` (#1612), `41017c289` (#1637) and `834c3086a`
  (#1641). Linear closed the issue Done the same day with the close comment.
