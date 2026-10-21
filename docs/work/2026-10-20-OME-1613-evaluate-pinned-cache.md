---
ticket: OME-1613
stack: screamingface
status: done
started: 2026-10-20
finished: 2026-10-21
---

# OME-1613 — replay a published run with `evaluate(pinned_cache=…)` and send author and paper metadata

## Intent

E14 (OME-1307) follow-up, SDK half. A researcher replays a published leaderboard run at $0 with
`sf.evaluate(pinned_cache="<id>")` and gets the results plus a verdict against the published
score. `sf.reproduce` is deprecated in favour of it. `submit` and `leaderboards.edit` gain the
`authors_metadata` and `paper_metadata` fields the scoreboard accepts (OME-1596, PR #1440).
Decisions S1–S9 are on the ticket; the spec is
`docs/spec/2026-10-20-OME-1613-evaluate-pinned-cache.md`.

## Planned changes

- `packages/screamingface/src/screamingface/client.py` — `evaluate` (sync and async): `pinned_cache`,
  `record_reproduction`, `candidates` optional when `pinned_cache` is given, `capture` default
  follows S6; `reproduce` deprecated.
- `packages/screamingface/src/screamingface/_reproduction.py` — a replay entry shared by
  `evaluate(pinned_cache=…)` and the deprecated `reproduce`; verdict and recording reused.
- `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` — the public pinned-cache
  lookup (`GET /v1/public/scores/by-pinned-cache/{id}`), metadata on submit and edit.
- `packages/screamingface/src/screamingface/report.py`, `leaderboard.py` — `pinned_cache` and
  `reproduction` fields; `frozen_copy_id` kept as a deprecated alias.
- Tests under `packages/screamingface/tests/` (see Test plan). Notebooks only if their output changes.

## Test plan

- RED first, against fake transports and a fake scoreboard (no network, no spend):
  - happy path: lookup → replay with the board's url4 and seed → `reproduction.outcome == "exact"`,
    recorded by default; `record_reproduction=False` records nothing.
  - S2: a passed `answer_seed` that disagrees with the board → error before any run.
  - S3: a passed url4 that differs from the board's → error before any run; omitted → board's used.
  - S4: lookup 404 with url4 + seed passed → replay runs, `reproduction` is `None`; without them →
    error naming what to pass.
  - S6: `pinned_cache` turns capture off; explicit `capture=True` with it → error.
  - a changed result → `failed` with its reason; a copy miss → `missed_cases`.
  - S8: `sf.reproduce` warns `DeprecationWarning` and still works; `frozen_copy_id` warns.
  - S9: metadata round-trips through submit and edit (wire payload asserted field by field).
  - invariant: no `pinned_cache` path ever schedules a run without the replay header.

## Acceptance

- As on the ticket. SDK gates green. Release only after OME-1596 is live in production.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** new `_scoreboard/replay_reads.py`, `_replay.py`, `_replay_partial.py`,
  `_scoreboard/credit_metadata.py`; changed `client.py`, `_default_client.py`, `__init__.py`,
  `errors.py` (`ReproductionError`), `report.py`, `leaderboard.py`, `_reproduction.py`,
  `_scoreboard/leaderboards.py`, `_evaluation/results.py`, `README.md`, `CHANGELOG.md`. New tests
  `test_replay_reads.py`, `test_pinned_cache_name.py`, `test_replay.py`, `test_evaluate_doors.py`,
  `test_evaluate_overload_types.py`, `test_replay_partial.py`, `test_submission_credit_metadata.py`;
  prior tests changed under `.claude/test-change-approvals/OME-1613.json`.
- **Commits:** `b5c362b62` score reads; `86d1c7504` rename (breaking); `cfb81ca9e` replay and
  removal of `sf.reproduce` (breaking); `dd220cf6d` partial replay; `f78275a82` metadata; plus the
  docs commit with this outcome.
- **Gates:** `run_gates.py screamingface --base origin/main` ALL GATES GREEN at every commit
  (pytest 4,303+ passed, 33 skipped, 97% coverage); `run_gates.py repo` green before the PR.
- **Deviations:** see the dated sections above: rows 3 and 4 in one commit; Q14 (raise when no run);
  `capture` default `None` with one prior test updated; the S4 hint is a warning; `url4.build` as
  the parser; `limit=` refused on the S4 path (pending owner review); `CandidateResult` gained a
  `reproduction=` keyword for the report store.

## Design review (owner, 2026-10-21)

- Taken over from the session that wrote the spec on 2026-10-20 (owner stopped it). Decisions Q1–Q10
  and resolutions R1–R4 are in spec §6. Ticket acceptance, S3, S4 and S7 updated in Linear to match.
- New scope from the review: `score_id=` (public read first, gated read on 404) for a private
  score's owner; `limit=n` partial replay that rebuilds the url4 and is never judged or recorded;
  two `@overload`s for the replay forms.
- Facts checked: the gated and public score reads both return the replay fields
  (`apps/scoreboard/src/scoreboard/scores/schemas.py` `ScoreSchema`); on production 2026-10-21 the
  public read returns all of them, and both captured rows have no `answer_seed` (omitted when null;
  the Engine then stamps no seed, `world/request_parameters.py` `apply_answer_seed`).
- Partial-replay feasibility (research 2026-10-21): the copy's replay key is the case id and Attempt
  (`docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` §5.4); the case
  count is stripped before the model input (`benchmarks/case_request.py`); nothing compares the url4
  against the copy (`apps/aigateway/.../frozen_copy/models.py`); n is written in several places of
  the url4 (`benchmarks/protocol.py:243-296`), so the SDK rebuilds rather than edits it.
- Follow-up filed: `OME-1699` (per-case results on the board); its mirror rides with this unit's docs.

## Breaking rename (owner, 2026-10-21)

- Row 2 showed that deprecating `frozen_copy_id` with a warning meant a hand-written ~25-field
  `LeaderboardScore` constructor and about 90 prior-test wraps (the suite turns this package's
  `DeprecationWarning`s into errors). The feature is one week old (0.1.3, 2026-10-14) and the SDK is
  pre-1.0, so the owner chose a hard rename and removing `sf.reproduce` now (spec Q12, Q13; ticket
  S7, S8 and acceptance updated). Plan rows 2 and 4 and its prior-test section amended. Option A's
  warning wraps are no longer needed; prior tests are renamed or migrated instead, listed in
  `.claude/test-change-approvals/OME-1613.json`.
- Public docs: four `public-docs` pages teach `sf.reproduce` or `frozen_copy_id`; `OME-1614` rewrites
  them (ticket updated the same day).

## Rows 3 and 4 (2026-10-21)

- **Deviation: plan rows 3 and 4 are one commit.** Removing `Reproduction.result` and the replay
  core touch the same prior tests; splitting them would migrate those tests twice.
- **Owner decision Q14:** a replay that cannot start (capture `partial` / unknown, or an Engine that
  refuses replay) raises `sf.ReproductionError` carrying the `Reproduction`; a `Report` always
  means a run happened. Spec §3 and §6 updated.
- **Owner decision on `capture`:** its default is `None` (meaning on), so an explicit `capture=True`
  on a replay can be refused (S6). The prior test that pinned the default `is True`
  (`test_frozen_copy_evaluate.py`) now pins `is None`, with a note; `test_evaluate_doors.py` proves
  a normal run still captures by default.
- **Deviation:** the S4 all-cases-missed hint is one `EvaluationWarning`, not a field on the result:
  that path has no verdict to carry it. Spec §4a updated.
- `Reproduction.result` removed (the result carries the verdict, `CandidateResult.reproduction`).
  `CandidateResult` gained a `reproduction=` keyword: the report store rebuilds results from their
  fields.
- `url4` equality uses `url4.build` (the url4 package's public parser; it has no top-level
  `parse`). Spec wording updated.
- `_replay.py` calls `_reproduction._classify` through the module, so the prior test that forces
  the verdict with `monkeypatch` still reaches it unchanged.
- Prior tests migrated (approval file): `test_reproduce.py` and `test_reproduce_review.py` drive the
  same replay through `replay_published_*` via `_reproduce` helpers; calls by id use
  `evaluate(score_id=…)`, and the one path assertion now expects the public read first (R2). The
  two tests of the removed `sf.reproduce` delegation are deleted; `test_evaluate_doors.py` checks
  that `reproduce` is gone from every door.

## Row 5: partial replay (2026-10-21)

- New `_replay_partial.py`: `limit=n` (1 <= n < published case count) rebuilds the url4 through the
  Engine catalog and the same `_prepare_benchmark(...).bind(candidate)` step the original run used.
  Guard: the whole run rebuilt at `limit=total_questions` must equal the published url4 as a parsed
  tree, else `PlanningError` `partial_replay_unavailable` before any run. Never judged or recorded.
- **Deviation, needs owner review:** `limit=` on the S4 path (no published score) is refused. The
  SDK knows no benchmark id there, and reading it from the url4's route text would be a text match.
  Spec R3 narrowed and marked pending.
- Tests: `tests/test_replay_partial.py` (fake catalog whose url4 depends on the asked limit: happy
  path, revision drift, protocol drift, bounds, types, S4 refusal, seedless run, async).

## Row 6: submission metadata (2026-10-21)

- New `_scoreboard/credit_metadata.py`: shape checks only (flat objects of text, finite numbers or
  booleans; `authors_metadata` one object per author email). The board's validator
  (`apps/scoreboard/.../scores/credit_metadata.py`) stays the authority on keys, bounds, matching
  and the paper link; the SDK copies none of those rules.
- `submit` (omit when None), `edit` (`_UNSET` keeps, None clears, an object replaces) on both
  clients; `LeaderboardScore.authors_metadata` / `.paper_metadata` decoded and frozen on read, so
  the metadata round-trips (ticket acceptance).
- Tests: `tests/test_submission_credit_metadata.py`.

## Independent code review (2026-10-21)

The `/code-review` skill reviewed PR #1519 at `5db7f453c` (high effort): 10 findings, no crash. The
owner had all 10 fixed in one commit:

1. The pinned-cache lookup is decoded like a score read: case digest shape and its capture status,
   and any malformed field is a Scoreboard `invalid_leaderboard` error, not a bare `ValueError`.
2. `limit`'s type and lower bound are checked in `_request`, before any board read or login.
3. Both replay warnings use `skip_file_prefixes=(SDK_PACKAGE_ROOT,)`, so they point at the
   caller's line (the "every case missed" hint showed only once per process before).
4. The url4 check compares the embedded Candidate recipe as a parsed tree too, and an unparseable
   published url4 is a `ValueError`.
5. The replay overloads accept `capture: Literal[False] | None`; `capture=True` stays a type error.
6. The async partial replay loads both catalog resources at once; the published url4 is parsed once.
7. The replay checks have one home: `Client._evaluate_replay` and a new `AsyncClient._evaluate_replay`;
   `sf.evaluate` reuses `client._evaluation_candidates`.
8. `replay_published_*` removed from `src`; the migrated tests drive `_plan` and `_run_*`.
9. `_edit_payload` calls the metadata value checks directly.
10. The `pytest.raises(match=...)` lines this PR changed assert the exact message instead.

Gates after the fixes: `run_gates.py screamingface --base origin/main` ALL GATES GREEN.

## Live check on staging (2026-10-21, branch at `b61ec9951`)

`sf.Client(engine_url="https://fusion.staging.screamingface.ai", scoreboard_url="https://leaderboard.staging.screamingface.ai").evaluate(pinned_cache="69a76841-73fc-47e8-8e6f-03796f6128c3")`
against a real Engine, gateway and board (the capture was made the same day by the OME-1649
staging check: score `5fc68454-338c-4645-bc10-a58b3e3a74e4`, 1 case, no seed).

- Lookup by pinned cache answered; the replay ran with no seed (the capture had none).
- Result: score 1.0 over 1 case, cost `0`, no capture on the replay run; replayed in 82.3 s.
- Verdict `exact`, no reason, no missed cases. The leaderboard login was asked for only then; its
  `redirect_url` was `/v1/scores/{id}/reproductions` (the #1486 fix on the recording path). After
  the owner's login: `recorded=True`, no `record_error`.
- The board reads back `reproduction_count: 1`, `last_reproduced_at: 2026-10-21T20:33:50Z`.
