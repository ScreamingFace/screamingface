---
id: OME-1935
linear_url: https://linear.app/openmined/issue/OME-1935/give-sfcredits-a-rich-notebook-repr-like-sfconnect
status: Done
type: feature
priority: high
labels: [client-sf, human]
parent: OME-1294
created: 2026-11-16
closed: 2026-11-17
---

# Give sf.credits() a rich notebook repr like sf.connect()

`sf.credits()` returns a plain `CreditStatus` dataclass. In a notebook it should render
a static card in the connection panel's credit style: account balance, key allowance,
hosted allowance, each state and its observation time.

Follow-on to E5 P3 (`OME-893`, `OME-1891`, `OME-1892`).

Spec: `docs/spec/2026-11-17-credits-repr.md`.
Plan: `docs/plan/2026-11-17-credits-repr.md`.
Ledger: `docs/work/2026-11-17-credits-repr.md`.
Branch: `OME-1935-credits-repr`.

Completed in [PR #1883](https://github.com/ScreamingFace/screamingface/pull/1883) (`3afc0ee29`). Linear reconciled to Done on 2026-11-18.
