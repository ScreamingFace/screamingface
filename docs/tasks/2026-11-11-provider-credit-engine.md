---
id: OME-1891
linear_url: https://linear.app/openmined/issue/OME-1891/expose-execution-scoped-credit-readings-through-the-engine
status: Done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1294
created: 2026-11-11
closed: 2026-11-16
---

# Expose execution-scoped credit readings through the Engine

Validated credit API tied to the execution connection, with hosted key-only privacy and local BYOK management controls.

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
