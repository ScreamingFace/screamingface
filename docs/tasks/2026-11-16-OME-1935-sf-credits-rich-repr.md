---
id: OME-1935
linear_url: https://linear.app/openmined/issue/OME-1935/give-sfcredits-a-rich-notebook-repr-like-sfconnect
status: Done
type: product-feature
priority: High
labels: [client-sf, human]
parent_epic: OME-1294
assignee: Filip Boltuzic
created: 2026-11-16
closed: 2026-11-17
---

# Give sf.credits() a rich notebook repr like sf.connect()

Follow-on to E5 P3 (provider credit visibility). `sf.credits()` returns a plain `CreditStatus`
dataclass; in a notebook it should render a rich visual card like the `sf.connect()` connection
panel does, showing account balance, key allowance, hosted allowance, states and `as_of`.

Reuse the existing connection-card credit panel visual language
(`packages/screamingface/src/screamingface/_ui/credit_*.py`). Credits API reference:
`/sf-client/api/credits`.

Completed in [PR #1883](https://github.com/ScreamingFace/screamingface/pull/1883) (`3afc0ee29`). Linear reconciled to Done on 2026-11-18.
