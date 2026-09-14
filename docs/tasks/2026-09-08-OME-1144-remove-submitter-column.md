---
id: OME-1144
linear_url: https://linear.app/openmined/issue/OME-1144/remove-the-submitter-column-from-the-leaderboard-table
status: Done
type: task
priority: 2
labels: [scoreboard, agentic, autonomous, BUG]
created: 2026-09-08
closed: 2026-09-09
---

# Remove the "Submitter" column from the leaderboard table

Drop the `Submitter` column from the benchmark leaderboard table. It duplicates `Authors`
(OME-1052) for every submission without an explicit author list, because `_resolved_authors` falls
back to `[submitted_by]`.

Portal display only. `submitted_by` stays on the model, the API, and the spec detail page.

## Artifacts

- Spec: `docs/spec/2026-09-08-OME-1144-remove-submitter-column.md`
- Plan: `docs/plan/2026-09-08-OME-1144-remove-submitter-column.md`
- Ledger: `docs/work/2026-09-08-OME-1144-remove-submitter-column.md`

Related: `OME-769` (added the columns), `OME-1052` (added Authors), `OME-1109` (author credit
publication, in flight).
