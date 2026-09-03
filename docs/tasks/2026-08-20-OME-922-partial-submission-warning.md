---
id: OME-922
linear_url: https://linear.app/openmined/issue/OME-922/warn-on-partial-submission-that-only-full-runs-are-ranked
status: in_progress
type: improvement
priority: 3
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-20
closed:
---

# Warn that partial-submission scores are not directly comparable

Warn at `sf.leaderboards.submit(...)` when a Candidate covers fewer than all Benchmark Cases or
has incomplete grading coverage. With ordinary warning policy the Client still sends the valid
submission unchanged; warnings-as-errors abort before the Scoreboard write.

In notebooks, explicitly display the branded advisory after publication so assignment and
notebook automation cannot hide it. Preserve `sf.EvaluationWarning` for headless callers and the
full Benchmark Case count when a Candidate Result is exported for later publication.

Canonical artifacts:

- Spec: `docs/spec/2026-08-20-OME-922-partial-submission-warning.md`
- Plan: `docs/plan/2026-08-20-OME-922-partial-submission-warning.md`
- Ledger: `docs/work/2026-08-20-OME-922-partial-submission-warning.md`
