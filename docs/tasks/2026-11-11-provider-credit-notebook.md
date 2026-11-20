---
id: OME-1892
linear_url: https://linear.app/openmined/issue/OME-1892/show-provider-credit-in-the-sdk-and-notebook-connection-card
status: Done
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1294
created: 2026-11-11
closed: 2026-11-16
---

# Show provider credit in the SDK and notebook connection card

Typed credit API, compact notebook card, visible-only five-minute refresh, and nonblocking recent-zero run notices.

Part of E5 P3. Related delivery units: OME-893 (Gateway), OME-1891 (Engine),
OME-1892 (SDK). All are assigned to Filip Boltuzic.

Spec: `docs/spec/2026-11-11-provider-credit.md`.
Plan: `docs/plan/2026-11-11-provider-credit.md`.
Ledger: `docs/work/2026-11-11-provider-credit.md`.
Branch: `OME-893-provider-credit`.

Merged in [PR #1753](https://github.com/ScreamingFace/screamingface/pull/1753) as
`95f172afdc77b1e0d9f60ee126db9307aeab4dc6`. Linear is Done.
Authenticated hosted dev verification passed on 2026-11-16 after the owner-authorized
replacement of the caller's stored OpenRouter credential with the verified team key.
Cached and fresh sync reads plus cached async SDK reads return a numeric allowance.
The notebook card shows one hosted allowance and hides the platform account balance.
Personal matching/mismatched key-pair checks also passed through the read-only
provider adapter. See the ledger for scope and remaining release/operator notes.
