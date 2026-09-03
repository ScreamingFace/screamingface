# OME-922 — Implementation plan

Spec: `docs/spec/2026-08-20-OME-922-partial-submission-warning.md` · Stack: screamingface

## Shape

Keep the advisory policy in a focused module at the Scoreboard submission seam. Synchronous and
asynchronous submission share one decision: headless callers receive `sf.EvaluationWarning`
before the POST, while notebooks reserve a rich notice and display it only after a successful
POST. The returned `LeaderboardScore` and HTTP payload stay unchanged.

## Tests first

Exercise the documented public workflows in a focused test module that proves:

1. A limited Candidate (`len(cases) < benchmark.case_count`, selected coverage `1.0`) warns
   and still posts the unchanged payload.
2. A full-sized Candidate with incomplete Engine coverage warns and still posts.
3. A full, fully graded Candidate emits no warning.
4. The async submission path has the same warning behavior.
5. A notebook assignment, final expression, sync call, and async call emit no Python warning and
   display the branded notice exactly once.
6. A notebook full submission omits the notice.
7. The README's `sf.leaderboards.submit()` facade attributes repeated warnings to each user line.
8. Warnings-as-errors abort before any POST.
9. Exporting and reconstructing a limited Candidate preserves the full Benchmark Case count.
10. Colab/Databricks subclasses of the ipykernel shell are recognised as notebooks.
11. A broken rich-display publisher falls back to stderr without hiding an already persisted id.

## Implementation

- Validate the Candidate and score as today.
- Determine partiality from selected Case count plus Engine coverage.
- Emit the exact ticket copy as `sf.EvaluationWarning` before a headless write; use Python 3.12's
  package-frame skipping so both the facade and explicit Client APIs point at the user's line.
- After a successful notebook write, explicitly display the notice so assignment and notebook
  automation retain it without relying on final-expression rendering.
- Render the notice with scoped canonical light/dark persimmon tokens and the product UI status
  recipe from `OpenMined/screamingface-brand` commit `7ea35a1`; do not recolour Report warnings.
- Preserve the complete Benchmark Case count in each exported Candidate Result while retaining
  the Report's selected Case count at the Report root.
- Reuse the validated score when constructing the payload.

## Verification

- Confirm the new tests fail before production changes and pass afterward.
- Run the full `screamingface` gate set through `.claude/scripts/run_gates.py`.
- Review the diff for unchanged full-run payloads and no Scoreboard-side changes.
- Capture a real IPython display event and confirm the notice reads as a branded warning, not a
  Jupyter exception banner, whether the score is assigned or left as the final expression.
