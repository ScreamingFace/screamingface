# B5 — SDK: send the cache version, and `sf.reproduce`

- **Worktree:** `.claude/worktrees/e14-b5-sdk-reproduce` · **Branch:** `e14-b5-sdk-reproduce`
- **Base:** `e14-a2-sdk-metadata` (A2 must be accepted first) · **Stack:** `screamingface`
- **PRDs:** `prd/cache-version-capture.md` (C4, C13, C14; TDD #14, #15) and `prd/reproduce.md`
  (R1–R11, R16, R20, R23, R24; TDD #15–#21, #23 SDK half). Contracts K3, K4, K7, K8. Rules: `00-common.md`.
- Engine (B3) and board (B4) are built on other branches. Code against `contracts.md`; fake the
  engine summary and the HTTP.

## Files

| File | Change |
|---|---|
| `src/screamingface/_core/ports.py` | `_RunOutcome.cache_revision: str \| None = None`, `reproducible: Literal["complete", "partial"] \| None = None` |
| `src/screamingface/_engine/contract.py` | read `cache.revision` and `cache.reproducible` from the run summary next to `cache.hits` (`_CACHE_HITS`) |
| `src/screamingface/_evaluation/results.py` | map them into `CandidateResult` (next to `cache_hits=outcome.cache_hits`) |
| `src/screamingface/report.py` | `CandidateResult.cache_revision`, `reproducible` (constructor params, validation, `to_dict`) |
| `src/screamingface/_scoreboard/leaderboards.py` | `_submission` sends `cache_revision`, `reproducible`, `answer_seed` when not None; `_decode_score` reads the B4 fields; new `record_reproduction(...)` (sync + async, internal) |
| `src/screamingface/leaderboard.py` | `LeaderboardScore` gains `cache_revision`, `reproducible`, `answer_seed`, `reproduction_count: int = 0`, `last_reproduced_at` |
| `src/screamingface/_engine/transport.py` | `X-Cache-Replay` header on the start call (mirror `_answer_seed_header`); read the ack header from the start response |
| `src/screamingface/reproduce.py` (new) | `Reproduction` + the outcome logic |
| `src/screamingface/client.py`, `_default_client.py`, `__init__.py` | `Client.reproduce`, `AsyncClient.reproduce`, module-level `sf.reproduce`; export `Reproduction` |
| failure-code declarations (`is_declared_failure_code`, `_report_primitives.py`) | declare `replay_cache_miss` and `unknown_cache_revision` the way other engine codes are declared |
| `tests/public_surface_snapshot.json` | regenerate (`UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py`) |
| tests | new files only |

## Decisions (pinned)

- `Reproduction` (frozen dataclass): `outcome: Literal["exact", "failed", "not_reproducible"]`,
  `reason: str | None`, `missed_cases: tuple[CaseId, ...]`, `result: CandidateResult | None`,
  `recorded: bool`, `record_error: str | None`. Reasons: `partial`, `unknown` (not_reproducible);
  `cache_miss`, `benchmark_revision_changed`, `score_differs`, `unknown_cache_revision`,
  `replay_unsupported`, `run_failed` (failed).
- `Client.reproduce(score: LeaderboardScore | UUID | str, *, record: bool = True) -> Reproduction`:
  1. A UUID/str → `self.leaderboards.get_score(...)`.
  2. `score.reproducible` is `None` → `not_reproducible/unknown`; `"partial"` →
     `not_reproducible/partial`. No engine call.
  3. Run through the same internal path as `evaluate(score.url4, answer_seed=score.answer_seed)`,
     with an internal `cache_replay=score.cache_revision` passed to the transport (not a public
     `evaluate` parameter). `cache_revision` None (empty run) → no replay header (R23).
  4. If a replay header was sent and the start response lacks the ack → cancel the run, return
     `failed/replay_unsupported` (R24). Find the existing cancel path; do not invent one.
  5. A pure function `_classify(score, result) -> tuple[outcome, reason, missed_cases]` in
     `reproduce.py`: any case failure with code `replay_cache_miss` → `failed/cache_miss` with those
     case ids; `unknown_cache_revision` → `failed/unknown_cache_revision`; run-level failure →
     `failed/run_failed`; `result.benchmark.revision != score.benchmark_revision` →
     `failed/benchmark_revision_changed`; `result.score != score.score` or case count ≠
     `score.total_questions` → `failed/score_differs`; else `exact`.
  6. `exact` and `record` → `record_reproduction(score.id, run_id=result.run_id, score=…,
     total_questions=…, cache_revision=score.cache_revision, client=…)`. Any exception from it
     (HTTP error or the SDK's typed errors) → `recorded=False`, `record_error=str(exc)`; never raise.
- `AsyncClient.reproduce` is the async twin. `sf.reproduce` follows how `sf.evaluate` is exposed.
- Submission fields are omitted when None (C13).
- The `LeaderboardScore` must expose `benchmark_revision` for step 5. If it does not today, add
  `benchmark_revision: str | None = None` and decode it from the board's `ScoreSchema`.

## Notes from B3 (engine, built)

- The engine emits `cache.revision`, `cache.reproducible` and `cache.partial.*` on the cache summary
  log line, which it emits **only when the run touched the cache**. So an absent
  `cache.reproducible` means "unknown" (older engine, or a run with no cache traffic): decode it as
  `None`. An empty run is therefore `not_reproducible/unknown` (accepted limit against C5/R23; drop
  the empty-run special case of step 3).
- The engine echoes `X-Cache-Replay: <label>` on the run-start response (202, and a finished sync
  result) when it accepted the header. Missing echo → cancel the run (step 4).
- Engine failure codes: `replay_cache_miss`, `unknown_cache_revision` (B3 `error_text.py`).

## Do not

- Do not add a public `evaluate(..., cache_replay=...)` parameter.
- Do not edit `CHANGELOG` files.

## Verify

`cd packages/screamingface && uv sync --extra runtime --extra notebook`, then
`python3 .claude/scripts/run_gates.py screamingface --base e14-a2-sdk-metadata`
