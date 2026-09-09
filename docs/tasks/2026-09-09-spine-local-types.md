---
id: OME-1150
linear_url: https://linear.app/openmined/issue/OME-1150/type-the-grading-spines-local-variables-and-land-the-rescued-candidate
status: in_progress
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous, task]
created: 2026-09-09
closed:
---

# Type the grading spine's local variables and land the rescued candidate-fields dataclass

Follow-up to OME-1097. PR #847 merged an older branch tip; the commit that replaced the
candidate-fields dict with a frozen dataclass (and made `output` honestly `str | None`)
survived only locally. Land it, then annotate the remaining non-trivial locals across
the spine modules so the `grade_case` seam states its own types before OME-1099 and the
inspect adapter build on it. Ledger: `docs/work/2026-09-09-OME-1150-spine-local-types.md`.
