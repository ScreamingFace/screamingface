---
id: OME-1756
linear_url: https://linear.app/openmined/issue/OME-1756/let-a-capture-run-record-picture-calls-up-to-the-gateways-request-size
status: done
type: fix
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1307
created: 2026-10-28
closed: 2026-10-28
---

# Let a capture run record picture calls up to the gateway's request size limit

A capture run records every model call into the AI Gateway's frozen copy, so the run can be
replayed later without calling a model. The gateway accepts a request of up to 8 MiB, but one
frozen-copy entry was capped at 2,000,000 B. Picture Cases carry their pictures inline (MMMU: 17 of
847 multiple-choice Cases; LAB-Bench FigQA and TableQA too), so those calls were answered but never
recorded, and their replay failed with `frozen_copy_miss`.

The entry cap now defaults to the request cap plus a 2 MiB response headroom (10 MiB), computed from
the request cap so raising one raises the other. Text-only entries are unchanged. No schema change.

That fits every picture Case we run (MMMU's largest is 3.78 MB), not every call the gateway accepts.
Two kinds of call are still answered but their capture reports `failed`: a cloud-provider response
over the 2 MiB headroom (only the local and remote-endpoint transports bound a response, at
1,000,000 B), and a request that grows when re-serialised (Python writes `1e9` as `1000000000.0`; a
body packed with such numbers went from 3,400,175 B on the wire to 11,050,175 B stored).

- Spec: `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` F3
- Ledger: `docs/work/2026-10-28-frozen-copy-fits-picture-calls.md`
