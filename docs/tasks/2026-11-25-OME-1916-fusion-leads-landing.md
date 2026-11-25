---
id: OME-1916
linear_url: https://linear.app/openmined/issue/OME-1916/show-leaderboards-where-fusions-outperform-solo-models-first
status: blocked
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

Design complete (see the ledger). Implementation is paused at the append-only test-change
gate: exposing the new `fusion_leads` field on `BenchmarkSummary` necessarily changes the
exact key set an already-committed test asserts on every `/v1/benchmarks/summary` row
(`test_catalog_summary.py::test_summary_matches_ranked_boards_and_omits_details`). Per this
repo's rigid-SDLC rule, an agent never self-approves a prior-test edit — this needs Filip's
own direct confirmation of the exact proposed diff (in the ledger's Outcome section), the
same way OME-1852's `.claude/test-change-approvals/` manifest was confirmed.

Parked in Triage pending that confirmation; not a blocked-by-another-ticket situation, so
the `blocked` label (which requires a named blocking ticket + relation) does not apply.

## Ledger

`docs/work/2026-11-25-fusion-leads-landing.md`
