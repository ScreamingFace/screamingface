---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-13
finished: 2026-10-13
---

# judge-row-review-fixes — the two review fixes rows 16 and 17 merged without

## Intent

OME-1527 Work order row 16b. #1389 (a pinned judge seed per pass, row 16) and #1390 (retrieval
policy declared on the row, row 17) merged before their review-fix commits were pushed. Both
fixes guard rows draco's migration (row 18) will declare, so they ship here, ahead of it:
a row that grades over judge passes refuses a judge call naming no pass, and a row that
declares a retrieval policy must pin its judge's web search off.

## Planned changes

- `judge_provider.py`: refuse an unseeded judge call on a `seed_per_pass` transport.
- `single_shot.py`: refuse, at assembly, a judged row with a retrieval policy whose judge
  params lack `('web_search', 'false')`; docstrings on `JudgeSpec` and `judge_redraw.py`.
- Tests appended to `test_judge_seed_per_pass.py` and `test_retrieval_policy_on_row.py`.

## Test plan

- The opted-in row refuses a judge call that names no pass, and no request leaves.
- A searching row whose judge pins search off assembles; one whose judge names no
  `web_search`, or `web_search=true`, is refused by name.

## Acceptance

- Both refusals pinned by tests; no published row's revision moves; every row still assembles.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus a review-fix note in each parent ledger
  (`2026-10-13-judge-seed-per-pass.md`, `2026-10-13-retrieval-policy-on-row.md`).
- **Commits:** the two fixes cherry-picked from the unpushed #1389/#1390 branches onto main;
  one conflict in `single_shot.py` resolved by keeping both refusals (#1387's envelope /
  check-surface refusal and this search refusal), then this ledger.
- **Gates:** relevant files only: `test_judge_seed_per_pass.py`, `test_retrieval_policy_on_row.py`,
  `test_judge_redraw.py`, `test_judged_benchmark_assembly.py`, `test_published_revisions.py`
  (every row assembles, revisions unchanged), `test_local_task_gdpval.py` (the conflict's other
  side), with the inspect extra: 132 passed. ruff + format clean; extra-less pyright 0 errors on
  touched files. Append-only check by hand (OME-1575): passes, tests are pure appends.
- **Deviations:** none.
- **Owner-verify:** nothing to press; no published row opts in to either. draco's migration
  (row 18) is the first row both guards check.
