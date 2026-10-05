# OME-1146 (part 2) — Drop the self-reported-costs disclaimer — Plan

Spec: `docs/spec/2026-09-29-OME-1146-drop-cost-disclaimer.md`

## Steps

1. RED: update `test_pareto_chart_shell_is_bounded_provenanced_and_loaded_before_its_caller`
   (flip the disclaimer assertion to absent) and rewrite
   `test_pareto_chart_heading_and_label_name_the_pareto_frontier` (docstring + assertion) for
   part 2's actual state. Add an assertion for the extended "Read this first" wording. Run,
   confirm both fail against the unchanged HTML.
2. GREEN: edit `apps/scoreboard/portal/benchmark.html` — extend the "Read this first" note
   (`:45-49`), remove the figcaption disclaimer (`:85`), remove the provenance comment
   (`:111-113`), remove the legend-item disclaimer (`:120`). Re-run tests, confirm green.
3. Grep sweep: `grep -rn "self-reported" apps/scoreboard/portal/ apps/scoreboard/tests/` — confirm
   only the now-updated test files and no other stray reference remains.
4. Full gates: `run_gates.py scoreboard --base origin/main`, expect the same append-only exception
   shape part 1 recorded (an existing assertion changing, not a new test's absence).
5. Fill the ledger's Outcome section, commit (`Refs: OME-1146`), open PR.
