---
id: OME-768
linear_url: https://linear.app/openmined/issue/OME-768/leaderboard-v1-landing-page-benchmark-catalog-benchmark-page-shell
status: done
type: task
priority: P1
labels: [scoreboard]
created: 2026-08-11
closed: 2026-08-12
---

Landing page (benchmark catalog: name, subtitle, submission count) + per-benchmark board shell
(tab strip, title/subtitle, empty table structure), scoped to DRACO + IFEval, rendering entirely
from the live API with `?id=` deep-linking. Bundled in the same unit: migrate
`apps/scoreboard/portal/` off its vendored SFDS v1 design system onto the current v2 marketing
register — the fix for Bennett Farkas's 2026-08-07 dated-design-system flag. Submission-row
population (OME-769), cost (OME-770), and the reproducible toggle (OME-771) are separate units.
Spec: `docs/spec/2026-08-11-OME-768-leaderboard-landing-benchmark-shell.md`.
