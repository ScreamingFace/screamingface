---
id: OME-1138
linear_url: https://linear.app/openmined/issue/OME-1138/aigateway-deprecate-profiles-and-converge-on-connections
status: in_progress
type: epic
priority: high
labels: [aigateway]
created: 2026-09-08
closed:
---

# AIGateway: deprecate Profiles and converge on Connections

Umbrella for removing the parallel Profile/ProfileIndex credential domain so Local and
Hosted deployments both use one canonical Connection per `(account, provider)` with OAuth
and API-key support, one shared credential resolver, and no `X-Profile` or selectable
Profiles in the target contract. Migration is additive, secret-aware expand/contract;
destructive cleanup waits for inventory, collision, consumer, coexistence and rollback
evidence. Blocks OME-1026 and OME-1035. Sub-issues are filed before code changes.

Ledger: `docs/work/2026-09-09-OME-1138-converge-connections.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md`.
Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md`.

Revision 2026-09-13: re-planned adapter-first — a provider-access boundary is introduced first,
backed by the existing Profile mechanisms; Profiles are not removed yet; the final backing
(Connections + slot, or a provider-account rework) is open (D11). First units await D7
re-approval; no sub-issues were created. Linear updated 2026-09-14: description section
"Adapter-first revision (2026-09-14)" appended and one comment added; status unchanged.

Execution approved 2026-09-14 (D7, D15, D17). Sub-issues: `OME-1198` (U0), `OME-1199` (U0e),
`OME-1200` (U1, blocked by the two Stage 0 units). Stop after A1 for review.

Stage 0 and A1 executed and committed 2026-09-14 (`OME-1198`, `OME-1199`, `OME-1200`): tests and
code green; stopped after owner review before A2. Stage 0 commits are `48fa1d78` and `c7d767f7`;
A1 is the OME-1200 feature commit. Details are in the ledger section "Stage 0 + A1 execution
(2026-09-14)".

A1 follow-up `OME-1204` (2026-09-15): provider-access modules and test helpers renamed without
leading underscores (owner decision D19); rename-only, OpenAPI byte-identical. Ledger
`docs/work/2026-09-15-OME-1204-rename-provider-access-modules.md`.
