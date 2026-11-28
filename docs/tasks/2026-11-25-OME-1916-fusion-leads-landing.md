---
id: OME-1916
linear_url: https://linear.app/openmined/issue/OME-1916/show-leaderboards-where-fusions-outperform-solo-models-first
status: in_review
type: feature
priority: 2
labels: [scoreboard, agentic, autonomous]
created: 2026-11-25
closed:
---

# Show leaderboards where fusions outperform solo models first

Parent epic: OME-1915 (Improve UX of the leaderboard E24).

Decided criterion (ticket body, 2026-11-25): a benchmark counts as a "fusion win" when the
best fusion score beats the best solo-model score on that benchmark, compared via
`classify_candidate_kind` (OME-1852) — never inferred from `spec_id`/provider count. Cost/
Pareto standing (OME-1282/OME-1852) is a separate, unrelated concept and is not reused here.

## Status (2026-11-25)

Implemented and all gates green. The append-only test-change question (see the earlier
revision of this file) is resolved: the owner created
`.claude/test-change-approvals/OME-1916.json` and applied the one-line edit to
`test_catalog_summary.py` directly; verified independently (blob hashes) before proceeding
rather than trusting the report alone. New fusion/model-grouping tests went into a separate
new file, `test_catalog_fusion_leads.py`, so the approved file's blob stays exactly the
approved one-line edit with nothing else appended.

PR open; ready for review and CI. Close this mirror and the Linear issue once merged.

## Ledger

`docs/work/2026-11-25-fusion-leads-landing.md`
