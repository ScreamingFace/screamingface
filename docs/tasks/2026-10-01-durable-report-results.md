---
id: OME-1448
linear_url: https://linear.app/openmined/issue/OME-1448/a-finished-evaluation-is-lost-when-the-notebook-runs-out-of-memory
status: in_review
type: task
priority: high
labels: [client-sf, agentic, design-session]
parent: OME-1294
created: 2026-10-01
closed:
---

# A finished evaluation is lost when the notebook runs out of memory while building its report

Selected recovery, bounded decoding and streamed export (A, B and D) are ready for
review in [SDK PR #1156](https://github.com/ScreamingFace/screamingface/pull/1156),
head `8a08d4c9`. Completion records precede verified streamed downloads; disk-backed
cases preserve full values/provenance; export streams through atomic replacement.
Derived indices are validated/rebuilt, nullable fusion summaries stream, saved listing
tolerates concurrent removal, and handled decode failures finalize lifecycle state.

All SDK gates pass; 39 new storage/accounting cases and 17 navigation cases passed.
The local synthetic 100,000-case fusion fixture used 55,787,520 bytes peak RSS and
verified full export/member totals. No new paid/hosted validation or rerun of the earlier
11 approximately 200 MB artifacts was performed during these final fixes.

Persistent local Engine storage is an independent slice in
[runtime PR #1217](https://github.com/ScreamingFace/screamingface/pull/1217), OME-1454.
Retention is unchanged; runtime persistence alone does not fulfill this ticket.
Schema-v2 prompt deduplication (C) is outside the selected implementation.

Linear reconciled to In Review on 2026-10-01, preserving assignee/labels/priority and
original description. Neither PR has merged. Evidence:
`docs/work/2026-10-01-sdk-derived-storage-hardening.md`,
`docs/work/2026-10-01-exact-case-navigation.md`, and the earlier recovery/presentation
ledgers linked in #1156. Linear remains the status authority.
