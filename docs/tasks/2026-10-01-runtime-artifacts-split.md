---
id: OME-1454
linear_url: https://linear.app/openmined/issue/OME-1454/persist-local-engine-artifacts-and-report-their-serving-directory
status: in_review
type: task
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1294
created: 2026-10-01
closed:
---

# Persist local Engine artifacts and report their serving directory

Extract the runtime artifact-directory slice from PR #1156 into an independently mergeable PR targeting main. Reader and writer use the same persistent default directory (0700), explicit nonblank overrides win, and status reads the serving runtime's recorded absolute path and current size from any working directory. Engine TTL and hosted storage are unchanged. SDK recovery/export/pagination remain in #1156.

All SDK gates and 20 focused runtime tests passed independently. Both merge orders compose without conflicts. The user approved title, parent epic, landing leaf and priority before creation. No paid model calls.

Spec/plan/ledger: `docs/{spec,plan,work}/2026-10-01-runtime-artifacts-split.md`.
