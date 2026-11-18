---
ticket: OME-1309
stack: scoreboard
status: in_progress
started: 2026-11-10
finished:
---

# SAD profile and dev acceptance

## Intent

Finish the owner-approved qualifying external-result test on dev using the previously audited SAD results. No production writes or paid model calls. Keep Linear unchanged until approved.

## Planned changes

Carry forward the reviewed local SAD evidence, import fixture, and pinned comparison profile onto current main. Preserve historical observation timestamps. Keep this change separate from edit history and the Source-button redesign.

## Test plan

Run the existing seven SAD regression cases before adding the profile (expected failure), then the complete scoreboard gates. Recheck current dev scope, metadata fields and fail-closed ranking. A live import requires verified firecall access and deployment of the new profile through the normal review/release process.

## Acceptance

A current-main, tested SAD profile and import fixture are ready for review. Report local validation separately from live acceptance; never patch a running service to bypass profile review.

## Outcome

Public dev check: UI eligibility guard is deployed; SAT trial rows have ranking_eligible=false and the new metadata fields. SAD remains revision c55f043049f958b9, 249 cases, no imported rows. Previous firecall address presents a changed host key; current verified access requested.

The qualifying import case failed on current main without the profile, then all seven SAD cases passed with it. Full scoreboard and repository gates passed, including the complete Python suite, coverage, all portal tests, formatting, lint and types. The public source table was rechecked on 2026-11-10 and still reports the same values and full dataset coverage. No dependency, schema or UI change. Existing tests were preserved.

Review: the profile pins exactly one board revision and source question set. The two observations preserve their original source-read dates, full historical evidence, and documented prompt differences. They are not auto-seeded. No running service was patched and no live import has occurred. Live acceptance remains pending verified dev access and normal deployment of this profile.

## Review follow-up (2026-11-17)

PR #1729 review (sergio-bershadsky) requested changes:

- **Blocking — fixed.** Both rows' `prompt_note`/`comparison_note` in
  `docs/imports/sad-facts-llms.json`, and the Prompts row in
  `docs/external-result-comparison.md`, now record the two open deviations from
  the Engine's fidelity record (`inspect-sad_facts_llms.md`, audited
  2026-11-09): D1, the system prompt reaches the Candidate as leading user-turn
  text instead of a system turn; D2, Task replay does not apply temperature 0.
  Added a link from the audit section to that fidelity record.
- **Non-blocking — fixed.** The count-conversion parametrized case in
  `test_sad_comparison.py` could not fail for its stated reason: the row's
  score (0.857) mismatched the converted value regardless of whether the
  `metric_name != "accuracy"` guard fired. Set the row's score to the correctly
  converted value and assert on the guard's message. Verified by temporarily
  removing the guard clause: the test now fails (confirmed), then restored.
- **Nit — fixed.** Added `match=` to the three bare `ValueError` asserts.
- **CodeQL failures on this head — investigated, unrelated.** All four
  `Analyze (*)` jobs fail at "Perform CodeQL Analysis" with the GitHub App
  installation's API rate limit exceeded (confirmed from the run log), not
  from anything in this PR's diff (docs/JSON/Python only, no Rust/JS touched).
  Flagging for a rerun rather than treating as a merge blocker.

`uv run pytest tests/unit/scores/test_sad_comparison.py` — 7 passed. Ruff
check and format clean on the touched file. Did not run the full scoreboard
gate: this branch is stale against current `origin/main` (unrelated append-only
drift from merged PRs), which is a separate rebase concern, not part of this
review-fix.
