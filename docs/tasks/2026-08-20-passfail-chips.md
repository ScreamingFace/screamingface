---
id: OME-900
linear_url: https://linear.app/openmined/issue/OME-900/show-passfail-on-rubric-criterion-chips-so-word-and-color-agree
status: in_progress
type: bug
priority: 3
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-20
closed:
---

# Show PASS/FAIL on rubric criterion chips so word and color agree

Rubric benchmarks (DRACO, HealthBench) have positive and negative criteria; the judge's
verdict is polarity-blind (MET = "the response did this thing"). The SDK report panel
prints that raw word but colors by score consequence — green UNMET / red MET chips on
negative criteria. Also: `_check_good` misses HealthBench's signed-`points` metadata, so
HealthBench negative criteria render the wrong color entirely.

Fix (display layer only, `packages/screamingface/.../_ui/report_view.py`): chip text
becomes derived PASS/FAIL (`PASS = positive∧MET ∨ negative∧UNMET`), color follows text,
the judge's raw MET/UNMET stays as subtext/tooltip, polarity reads both `criterion_type`
and `points` sign. Stored/archived verdicts never rewritten.

Ledger: `docs/work/2026-08-20-OME-900-passfail-chips.md`. Full spec in the Linear issue.
