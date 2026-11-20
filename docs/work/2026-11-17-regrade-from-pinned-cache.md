---
ticket: OME-1909
stack: screamingface-engine
status: done
started: 2026-11-17
finished: 2026-11-17
---

# regrade-from-pinned-cache — re-grade an old leaderboard entry from its pinned cache after a revision bump

## Intent

A grading fix that keeps every Case (OME-1907's wrapped-letter rule, 47 rows) either mixes two
gradings under one published revision or, if the revision moves, empties the board, because each
board shows only its current revision. This unit adds a **re-grade**: replay an old entry's
pinned cache under the bumped revision at no model cost and submit a new entry linked to the old
one. It ships in one PR after #1783 (OME-1907), with the rule change that makes a grading change
move the revision (owner, 2026-11-17). The bump of OME-1907's 47 revisions was built here and
moved to OME-1958 on 2026-11-18 (see the last outcome bullet).

## Planned changes

- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md`: the revision rule now moves
  the id on a grading change, not only on a changed Case set (owner decision, 2026-11-17).
- `apps/screamingface-engine/scripts/benchmark_bump.py`: the WARNING and checklist say the same,
  with a re-grade step after the deploy.
- `apps/screamingface-engine/tests/unit/inspect/test_benchmark_fingerprints.py`: the docstring
  and failure message say the same (prior-test edit: approval manifest with the bump).
- Re-grade itself: Engine (serve the Case Digest and the revisions a row may be re-graded from),
  SDK (`Client.regrade`), Scoreboard (re-grade route, `regraded_from` / `regraded_by`, team
  allowlist), and the bump of the 47 revisions. Plan to follow on OME-1909 before any code.

## Test plan

- `tests/unit/inspect/test_benchmark_bump.py` still passes with the reworded WARNING.
- Re-grade tests: written with the plan.

## Acceptance

- The rule, the bump command and the fingerprint test all say a grading change moves the id.
- A re-grade of an OME-1907 entry under the bumped revision submits a linked entry at $0.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - Rule (4856d193d): `docs/adding-an-imported-benchmark.md`, `scripts/benchmark_bump.py`, `test_benchmark_fingerprints.py` docstring and failure message. Plan (9416ab926): `docs/plan/2026-11-17-regrade-from-pinned-cache.md`.
  - Engine, old revisions served (2f83f6bfa): `benchmarks/definition.py`, `screamingface_engine_inspect/benchmarks.py` (`BenchmarkSpec.regradable_from`, assembly refuses a stale Case Digest), `single_shot.py`, `test_regradable_from.py`.
  - Engine, live judges on a replay (8e3fe0295, 347585e78; REMOVED 2026-11-20, see the last bullets, now OME-1979): `adapters/inprocess.py`, `adapters/queue_runner.py`, `job_env.py`, `ports.py`, `request_scope.py`, `rest/routes.py`, `runner/main.py`, `runner_queue.py`, `world/connector.py`, `test_replay_live_judge.py`.
  - Scoreboard re-grade route (90b46ac38, dd6207f48): `config.py` (`regrade_identities`), `routes/scores.py`, migration `0025_score_regraded_from.py`, `scores/models/score.py`, `scores/schemas.py`, `scores/store.py`, `test_regrade_route.py`, `test_migration_0025_score_regraded_from.py`.
  - SDK `Client.regrade` (7afae6a9f, a89cd34ee): `_regrade.py`, `client.py`, `errors.py`, `_core/wire.py`, `_engine/catalog_contract.py`, `_engine/transport.py`, `_evaluation/benchmark.py`, `_evaluation/model.py`, `_evaluation/url4.py`, `_scoreboard/leaderboards.py`, `_scoreboard/replay_reads.py`, `CHANGELOG.md`, `tests/unit/test_regrade.py`.
  - Bump of the 47 revisions (2347b5810): the 47 rows in `screamingface_engine_inspect/benchmarks.py` (`published_revision` + `regradable_from`), `test_published_revisions.py`, the OME-1907 comment in `test_benchmark_fingerprints.py`, Engine `CHANGELOG.md`.
  - Prior-test edits (83fdb60dc): `test_benchmark_foundation.py`, `test_leaderboard_routes.py`, `public_surface_snapshot.json`, approval manifest `.claude/test-change-approvals/OME-1909.json`.
- **Commits:** 4856d193d, 9416ab926, 2f83f6bfa, 8e3fe0295, 347585e78, 90b46ac38, dd6207f48, 7afae6a9f, a89cd34ee, 2347b5810, 83fdb60dc, and this docs commit, on top of #1783.
- **Gates:** Engine with the inspect extra: 250 passed in `test_published_revisions.py`, `test_published_revision.py`, `test_benchmark_fingerprints.py`, `test_regradable_from.py`, `test_benchmark_bump.py`, `test_benchmark_foundation.py`; all 47 rows assemble, serve their new revision and list their old one. Scoreboard: 93 passed in `test_leaderboard_routes.py` and `test_regrade_route.py`. SDK: 59 passed in `test_public_surface.py` and `test_regrade.py`. ruff check and format clean on the touched Python files. The append-only check (vs main at a23e84311) passes for the Engine, Scoreboard and SDK stacks with the OME-1909 manifest. Each task's own test runs are in its review.
- **Deviations:** no `to_dict` on `Benchmark`: the `regradable_from` key is emitted through `_metadata`. The Engine echoes the live set in `X-Replay-Live-Judge`, and the SDK refuses a re-judge when an Engine does not echo it. `regraded_by` is stored but on no read schema. A repeat re-grade answers 409 with `existing_score_id`. A re-grade reads only public scores. With `live_judge` set, any failure on a live-judged Case refuses the re-grade. The CHANGELOG names the 47 rows in one line; per-row old ids live in `test_published_revisions.py` comments. The manifest also pins #1783's two test edits, since `OME-1907.json` names #1783's branch.
- **Final review fixes (0db49acea, 7752f50b3, 8ffec4250, 8ab928bb7, and this docs commit):** the judged-recipe live-judge cases moved to the inspect lane (removed with live judging on 2026-11-20) (`tests/unit/inspect/test_replay_live_judge_recipe.py`); the bump command and the rule doc print the `regradable_from` line a move needs (medxpert has no such path yet); the Scoreboard chart renders `config.regradeIdentities` (empty by default) as `SCOREBOARD_REGRADE_IDENTITIES`, checked by `verify_chart_wiring.py`; a source may be re-graded once per revision (unique on `regraded_from` + `benchmark_revision`, migration 0024 edited in place, not yet deployed); the route refuses a body whose `total_questions` differs from the source's (422 `different_case_count`); the SDK decodes `regraded_from`, refuses a re-grade of a re-grade (`regrade_the_source`, naming the root), and runs with the gateway cache off when `live_judge` is set; the catalogue-entry `regradable_from` decode is gone (the resource keeps it); OME-1907's CHANGELOG line, mirror and ledger now say the revisions move here.
- **Merge up, 2026-11-18:** #1783 and #1892 (OME-1708) landed on main first, so the PR now targets main and merges main in. The migration became `0025_score_regraded_from.py`, after #1892's `0024_benchmark_revisions`. OME-1909.json is re-pinned against main at d4848c55d (eleven files; #1783's `test_scorer_source_pins.py` edit is on main now). Review fixes (Sergey): a re-grade stores the source's four cost fields, since a replay reports an unpriced `partial` and the entry would otherwise leave the cost ranking for good (`test_a_regrade_keeps_the_sources_cost_not_the_replays_unpriced_one`); the `regradable_from` comment, its test docstring and the rule doc now say the digest pair catches only a Case change made after the bump (the pinned-cache miss catches an earlier one). The re-grade link is published on the score read only, not on the board entry; showing it on the board is OME-1708's frontend. Gates: Scoreboard 126 passed (re-grade route, migration 0025, leaderboard routes, revision tests); Engine with the inspect extra 288 passed; SDK 104 passed (`test_regrade.py`, surface messages, public surface).
- **Known limitations:** a Benchmark whose judge request changed cannot be re-graded (every judged Case misses the copy) until OME-1979. Deleting a source score (SET_NULL) leaves its re-grade standing as a plain entry with no link.
- **Bump moved out, 2026-11-18 (owner):** commit 2347b5810 (the 47 `published_revision` + `regradable_from` rows, `test_published_revisions.py`, the OME-1907 fingerprint comment, the CHANGELOG line) is reverted here and re-applied in OME-1958's PR. Why: this PR then moves no leaderboard when it deploys, and the bump merges and deploys right before the batch re-grade, so old entries are off the Latest board for minutes. The OME-1907 mirror, ledger and the rule doc now name OME-1958 for the move; OME-1909.json drops `test_published_revisions.py`.
- **Live judge moved out, 2026-11-20 (owner):** Filip's review found that a partial re-judge sends today's judge request for the Cases it does not name, so after a `max_tokens` raise every unnamed Case misses the copy. The live judge mode (Engine `X-Replay-Live-Judge`, SDK `live_judge`, their tests and the six job-runner fake edits) is removed here and moves to OME-1979; the Engine source matches main except `regradable_from`. A re-grade now replays every call; a Benchmark whose judge request changed cannot be re-graded until OME-1979. HLE keeps its revision for OME-1939's judge-cap raise (owner, 2026-11-20), recorded as a named exception in the rule doc. OME-1909.json now pins four files. Gates: SDK 83 passed (`test_regrade.py`, public surface, surface messages), Scoreboard 23 passed (`test_regrade_route.py`), Engine 246 passed (revision tests); ruff and pyright clean on the touched SDK files.
- **Review round 3 (2026-11-20):** (1) a re-grade now refuses, retryably, any run-level failure and any Case failure a stored reply does not explain (only `provider_refusal`, `model_token_cap`, `model_empty_content` and `judge_reply_invalid` replay as the source's own), so a timeout or a raising grader never posts a lower score under the researcher's name; 5 new tests fail with the check disabled. (3) the board's environment refusals (401, `not_allowed`, `regrade_unavailable`, `not_current_revision`) are retryable in the SDK, so a batch run before the deploy catches up retries them. (4) the board refuses a re-grade of a re-graded row (`regrade_the_source`) and a body whose `models` differ from the source's (`different_models`); `spec_id` is not compared yet, because its stability across a re-grade is not verified (the dev re-grade will show it). (2) a re-graded row keeps the source's `submitted_at` (owner, 2026-11-20), so tied specs keep ranking by the earlier claim and the frontier trend keeps its dates; pinned by `test_tied_regrades_rank_by_their_sources_dates_not_the_batch_order`, which fails without the copy. (5) one real re-grade on dev is the owner's. Gates: SDK 140 passed (`test_regrade.py`, `tests/test_leaderboards.py`), Scoreboard 26 passed (`test_regrade_route.py`).
- **Owner verify:** set `regrade_identities` per environment: OpenMined/infrastructure#2382 lists seven team emails on dev, staging and production. The bump of the 47 revisions, the team post and the batch re-grade are OME-1958.
