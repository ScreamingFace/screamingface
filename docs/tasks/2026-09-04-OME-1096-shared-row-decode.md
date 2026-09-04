---
id: OME-1096
linear_url: https://linear.app/openmined/issue/OME-1096/share-the-row-decode-and-index-step-between-gdpval-and-healthbench
status: in_progress
type:
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-04
closed:
---

# Share the row decode and index step between gdpval and healthbench

Second code PR of the OME-1024 spine chain. The step that reads a fan-out's collected rows
back — parse the array, guard the count against the roll call, notice an outer error, file
each row under its Case id — existed twice, near byte-identically, because `gdpval/` was
forked from `healthbench/` two weeks ago. It now lives once in
`benchmarks/spine/rows.py` as `RowReader`, with the three board-varying bits injected at
construction (`benchmark_label`, `error_type`, `decode_case_evaluation`), matching the
`CaseGrader` precedent from OME-1039. Both copies deleted; every pre-existing test passes
unmodified, which is the proof nothing observable moved.

Design decision (owner-approved in session): the row stays an **opaque** board-owned
mapping. The ticket's review note asked for kind-tagged payload types (`kind: "text"`);
deferred deliberately because these functions never open the envelope, and inventing the
kind vocabulary here would pre-empt `OME-1103`, the design session that exists to decide
it. The invariant is recorded as an `INVARIANT:` anchor in the new module.

Ledger: `docs/work/2026-09-04-OME-1096-shared-row-decode.md`
