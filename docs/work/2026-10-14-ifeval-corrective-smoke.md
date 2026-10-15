---
ticket: OME-1527
stack: screamingface
status: done
started: 2026-10-14
finished: 2026-10-14
---

# ifeval-corrective-smoke — the paid Benchmark smoke also runs ifeval as a Corrective Loop

## Intent

OME-1527 row 15b (PR 15b of 20, stacked on #1407, owner's request). The paid smoke runs every
picked Benchmark as a Fusion only, and a Fusion never calls the Benchmark's mid-run check, so
ifeval's Draft Feedback chain is never exercised live: the checker's words about failed
requirements → the check route → the judge's coaching → the retry prompt carrying the coaching
and the previous answer. When ifeval is picked, the press now also runs it as a Corrective Loop,
its own entry `ifeval · corrective loop`, with weak members so round 1 is likely to fail, and
reads each Case's rounds back from the kept Report to show whether the chain ran.

## Planned changes

- `packages/screamingface/tests/paid/_panel.py`: the loop's roster (members, judge, rounds,
  Case limit, with the evidence), `corrective_loop()`, and `SmokeRun` (how an entry runs: which
  Candidate, how many Cases, its label and Report name) with `FUSION_RUN` / `CORRECTIVE_RUN`.
- `_scope.py`: `ShelfPick.corrective` — `["ifeval"]` exactly when ifeval is picked.
- `_corrective_chain.py` (new): read each Case's `rounds_executed` / `stop_reason` from the kept
  Report, print one line per Case, and the "chain not exercised" warning when none got past round 1.
- `_board_summary.py`: a `warnings` field on the overview, printed under the entry, in the
  end-of-run block and under the Markdown table; never a failure.
- `test_imported_board_smoke.py`: run entries (Benchmark, `SmokeRun`) instead of bare Benchmarks;
  the referee takes the expected Case count; provenance reads the picked Benchmark ids.
- Workflow header comment mentions the extra entry.

## Test plan

- `test_panel_models.py`: the loop's members and judge are gateway seeds; the built loop is the
  golden's members, prompt and params with a prompt-less, non-reasoning judge and 3 rounds.
- `test_scope.py`: naming ifeval, or a scope that picks it, adds the loop entry; a pick without
  ifeval does not.
- `test_corrective_chain.py` (new): a canned Report with a 3-round Case → exercised, no warning;
  all 1-round → warning; a Case with no loop outcome is not counted; no kept Report → no warning;
  an infrastructure code on the loop → a red problem named by the entry; the loop entry asks
  evaluate for a CorrectiveLoop on ifeval with 8 Cases and keeps `ifeval.corrective-loop.json`.
- `test_board_summary.py`: a warning keeps the board ok and shows in the log block and on the
  run page, under the table.

## Acceptance

- `benchmarks=ifeval` runs two entries: `ifeval` (Fusion, 2 Cases) and `ifeval · corrective
  loop` (8 Cases); a pick without ifeval runs no loop.
- The loop entry fails the press on the same infrastructure codes as every entry, keeps its Report
  beside the others, and prints per Case: rounds, whether the check passed, the Case status.
- No Case past round 1 → a loud `chain not exercised` warning in the press overview, not a red press.
- Every model the loop calls is a gateway seed, pinned for free.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1527.json` (rewritten for
  this branch: `_board_summary.py`, `_scope.py`, `test_imported_board_smoke.py`; while stacked,
  it also carried #1407's entries, dropped once #1407 merged into main on 2026-10-15).
- **Models:** members `mistralai/ministral-3b-2512` and `microsoft/phi-4` (the recorded ifeval
  golden's members, seeded as "IFEval-fallible by design", non-reasoning; recorded prices
  $0.10/$0.10 and $0.07/$0.14 per million tokens in/out), with the golden's member prompt and
  params (max_tokens 8192, temperature 0) so round 1 sends the bytes that failed when recorded.
  Judge `anthropic/claude-haiku-4.5` (non-reasoning, already in every press; about $1/$5 per
  million): the golden's judge, `deepseek-v4-flash`, is a reasoning model whose coaching reply on
  Case 10 came back empty (`model_token_cap`) and which wrote an answer instead of coaching on
  Case 6. A bad tie-break label never fails a Case: the engine falls back to the first passer.
- **Case limit 8 — evidence:** the tape (`ifeval.snapshot.gz`, 177 rows: 66 per member, 45 judge)
  keeps responses only, not prompts, so "Your previous answer:" cannot be searched. The response
  timestamps can: round 1 of all 50 Cases ran in Case order in one recording session
  (1788948138–1788949444: 99 member replies and 21 tie-break labels; Case 16's missing ministral
  reply was re-recorded in the second session with its tie-break), and every later-round call sits
  in a second session (1789015837–1789017430) as coaching reply → both members' retries, whose
  answers match these Cases' prompts: Case 6 (3 bullets, ball gown vs sweats) 3 rounds, Case
  8 (Matthias Algiers resume, fewer than 10 all-caps words, in quotes) 3 rounds, Case 12 3, Case 24
  3, Case 26 3, Case 34 3, Case 41 2, Case 43 3, Case 49 2; 16 coaching replies and 16 retry pairs in all
  (132 member replies − 100 round-1 ones = 32). Case 10 also failed round 1, but its coaching reply was the empty
  one, so it failed instead of retrying. 8 is the smallest N whose first N Cases hold two
  multi-round Cases (6 and 8).
- **Chain evidence from the Report:** each Case's `rounds_executed` and `stop_reason`. The Report
  keeps no check record and no coaching text, so a Case with 2+ rounds is the proof: a loop only
  reaches round 2 through the coaching call (inside the gate a no-pass round opens; a failing
  coaching call fails the Case). The coaching text being non-empty is not provable from the Report.
- **Cost per press (the loop entry):** recorded tokens for Cases 1..8 with the judge repriced to
  haiku: members ~$0.002 (24 calls), judge ~$0.013 (4 coaching + 3 tie-break calls) → about 1.5
  cents. Ceiling if every Case runs 3 rounds: 48 member calls + 16 coaching + 8 tie-breaks ≈ 7 cents.
- **Commits:** see the PR.
- **Gates:** relevant files only, with `SCREAMINGFACE_TEST_PAID=1` and no key:
  `test_panel_models`, `test_scope`, `test_board_summary`, `test_corrective_chain`,
  `test_report_export`, `test_parallel_board_worker`, `test_no_graded_case_message`,
  `test_progress_line`, `tests/test_paid_lane_isolation.py`: 54 passed. The paid test collects
  (1 test). ruff + format clean, pyright 0 errors on the 9 touched files. Mutation checks (edited
  back in place): round threshold 2→1, a pick that never adds the loop, the loop running
  CASE_LIMIT Cases, and dropping the end-of-run warning each turn a test red. A dry run of the
  shelf runner with fake clients printed both entries, the per-Case lines and the warning, and
  kept `ifeval.json` beside `ifeval.corrective-loop.json`. Append-only check by hand (OME-1575),
  against the parent branch and against main's merge base: passes through `OME-1527.json` except
  #1407's deleted and renamed engine tests, which no manifest can approve (as on #1407). After
  #1407 merged and main was merged in, the check against main passes with no exceptions.
- **Deviations:** none from the brief. The tape could tell which Cases retried (by time order and
  answer content), so the limit comes from the tape, not from the golden's statuses.
- **Owner verify:** after #1407 and this PR merge, press the paid smoke with `benchmarks=ifeval`
  and read the `ifeval · corrective loop` lines: expect Case 6 and Case 8 at 2–3 rounds; a
  `chain not exercised` warning means both passed round 1 on that press.
