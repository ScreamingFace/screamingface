---
id: OME-1370
linear_url: https://linear.app/openmined/issue/OME-1370/import-benchmarks-whose-eval-doesnt-name-its-judge-model-starting-with
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-09-25
closed:
---

# Import benchmarks whose eval doesn't name its judge model, starting with SimpleQA

Most inspect judges ask for "the grader" (`get_model(role="grader")`) and don't name a model.
Outside inspect's own eval loop nobody fills that role. This ticket binds the role to our
metered gateway judge for the grading pass, then imports SimpleQA as the first board.

- 2026-09-25: filed as an `OME-1240` follow-up.
- 2026-09-29: scoped the first PR to the mechanism only (ticket comment). A board row may
  declare `JudgeSpec(model=..., model_role="grader")`. The judged aggregate binds the role for the
  grading pass, and assembly cross-checks the role declaration. This covers acceptance 1 and 3.
  Branch `OME-1370-grader-role-judge`, ledger
  `docs/work/2026-09-29-ome-1370-grader-role-judge.md`.
- Still open, acceptance 2 (the SimpleQA board). Three things block it: its CSV data waits on
  `OME-1273`'s non-Hub loader lane; its paper scorer returns a dict score the shim can't map
  (follow-up to file); and its default scorer calls the judge with tools, so the board must
  pin `scorer="original"`.
