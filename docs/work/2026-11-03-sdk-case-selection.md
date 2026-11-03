---
ticket: OME-1739
stack: screamingface
status: done
started: 2026-11-03
finished: 2026-11-03
---

# sdk-case-selection — `sf.evaluate(..., cases=[3, 17, 42])` (OME-1739, PR 2 of 2)

## Intent

A researcher runs a Benchmark on a fixed list of Case ids (a development set, then a held-out
set) instead of the first N. PR 1 (#1636) taught the Engine to serve, grade and echo a posted id
list. This PR is the SDK half: `cases=` beside `limit=`, the POST to the Engine's selection
route, a refusal when the Engine does not echo the list (an older Engine would otherwise run and
bill the whole Benchmark), a refusal when the graded Cases differ from the request, the selection
on the Report with a fingerprint a paper can cite, and a refused leaderboard submit.

## Planned changes

- NEW `packages/screamingface/src/screamingface/_evaluation/case_selection.py`: door check
  (ints, distinct, >= 1, at most 1,000, not with `limit=`), the fingerprint, the roll-call
  positions a result graded.
- `_engine/benchmark.py`: POST `/v1/benchmarks/{id}/selection` with `{"cases": [...]}`.
- `_evaluation/benchmark.py`: the echo check (`selected_case_ids` must equal the request).
- `_evaluation/model.py`, `_evaluation/compilation.py`: the Evaluation carries the selection.
- `_evaluation/runner.py`: thread `cases`, refuse a Report whose roll call differs (F6).
- `client.py`, `_default_client.py`: `cases=` on the Recipe overloads (sync + async); refused
  with a complete URL4 and with a replay.
- `report.py`: `CandidateResult.selected_cases`, `Report.selected_cases`,
  `Report.selection_fingerprint`.
- `_scoreboard/leaderboards.py`: submit refuses a selected run.

## Test plan

- New `tests/test_case_selection.py`: happy path (3 Cases run, Report names them, fingerprint),
  the POST body, F1 (0, duplicate, bool, non-int, with `limit=`), F7 (1,001 ids), F2 (Engine
  without the echo, and an echo of other ids), F3 (422 relayed before any run), F6 (graded
  roll call differs), F4 (submit refused), `limit=` still a GET with no selection, async twin,
  a complete URL4 and a replay refuse `cases=`.

## Acceptance

- A selected run asks the Engine for exactly the posted ids and its Report names them.
- No run starts against an Engine that did not echo the selection.
- A selected CandidateResult cannot be submitted.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `CHANGELOG.md` (Features entry), the regenerated
  `tests/public_surface_snapshot.json` (additive rows only) pinned by
  `.claude/test-change-approvals/OME-1739.json`, and the task mirror closed.
- **Commits:** `feat(screamingface): run a fixed list of Case ids with evaluate(cases=...)`.
- **Gates:** owner rule, relevant tests only: 391 passed across the 16 test files that cover
  the touched modules (Client run, replay, partial replay, reproduce, leaderboards, report,
  compilation, catalog, public surface, the new `test_case_selection.py`); ruff check + format
  and pyright clean on the 11 touched files. A mutation that let any echo through failed
  `test_a_resource_that_does_not_echo_the_selection_is_refused_before_any_run[other]`.
  The full gate (coverage floor, notebooks, build) is CI's.
- **Review round 1 (#1653):** an Engine older than OME-1739 answers the selection POST with the
  router's bare 404, which read as "Benchmark not installed"; now `engine_cannot_select_cases`
  names the Engine, while the Engine's own "Unknown benchmark" 404 keeps `unknown_benchmark`.
  The 1,000-id cap is bound to the Engine's `MAX_SELECTED_CASE_IDS` by a source-parsing
  conformance test (a 1,001 mutation fails it). 393 passed in the same files plus the new one.
- **Deviations:** partial replay with `cases=` (architecture box 9 on the ticket) is refused
  with a plain error instead of built; the researcher's flow does not need it and it keeps the
  PR small. `selected_cases` is derived from the roll call, sorted, so a full run listed out of
  order still reads as a full run. Owner verify after merge: deploy the Engine (#1636) before
  releasing this SDK, since an SDK `cases=` run against an Engine without the route is refused.
