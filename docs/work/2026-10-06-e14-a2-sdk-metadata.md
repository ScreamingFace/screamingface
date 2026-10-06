---
ticket: unfiled
stack: screamingface
status: in_progress
started: 2026-10-06
finished:
---

# e14-a2-sdk-metadata — SDK paper link, edit and metadata events

## Intent

E14 PR A2 (spec `docs/spec/2026-10-06-e14-reproducible-submission/prd/metadata-ownership.md`,
contracts K4, K5, K6, K8). A researcher who submits before the paper exists must be able to add the
paper link and fix authors later. The SDK gains `submit(..., paper_url=)`, `leaderboards.edit(...)`
and `leaderboards.metadata_events(...)`, and `LeaderboardScore` reads `paper_url` and
`metadata_updated_at`. The scoreboard half (A1) is built in parallel; the HTTP is faked with
`httpx.MockTransport`.

## Planned changes

- `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py`: `paper_url` on `submit`;
  `edit` and `metadata_events` on both classes; `_decode_score` reads the new fields;
  `_decode_metadata_event`; operation codes in `_status_code`.
- `packages/screamingface/src/screamingface/leaderboards.py`: module-level `edit` and
  `metadata_events`; `__all__`.
- `packages/screamingface/src/screamingface/leaderboard.py`: `LeaderboardScore.paper_url`,
  `metadata_updated_at`; new `ScoreMetadataEvent`.
- `packages/screamingface/src/screamingface/__init__.py`: export `ScoreMetadataEvent`.
- `packages/screamingface/tests/public_surface_snapshot.json`: regenerated (documented path).
- `packages/screamingface/tests/test_leaderboards_metadata.py`: new, append-only.

## Decisions recorded (coordinator answers, 2026-10-06)

- Q1: module-level `sf.leaderboards.submit` gains `paper_url: str | None = None` and forwards it only
  when it is not None (absence stays absence, so older or fake Leaderboards keep working). The
  existing delegation test is not edited.
- Q2: `edit` 404 uses `("unknown_score", ...)`, the same as `get_score`. `metadata_events` 404 uses
  the same code.
- Sentinel: `_Unset` class with a stable `UNSET` repr in `_scoreboard/leaderboards.py`, imported by
  the public wrapper.

## Test plan

- PRD TDD #19: `submit` sends `paper_url` only when given; client-side check (http/https, 1-2048).
- PRD TDD #20: `edit` sends PATCH and decodes the score (sync and async); argument rules.
- PRD TDD #21: `edit` maps 403, 404, 422 to typed errors; events 403.
- PRD TDD #22: `metadata_events` decodes the list; empty list; older board omits the new fields.

## Acceptance

- Gates for stack `screamingface` pass against base `e14-reproducible-submission-spec`.
- No existing test edited or removed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (six files: the three `src/screamingface/` modules, `__init__.py`,
  the regenerated snapshot, the new test file), plus this ledger.
- **Commits:** `feat(screamingface): add paper link, score edit and edit log to the SDK`; this ledger.
- **Gates:** `run_gates.py screamingface --base e14-reproducible-submission-spec` FAILS the
  append-only check on `tests/public_surface_snapshot.json` (a regenerated snapshot, the plan's
  documented update path). With `--skip-append-only`, every other gate is green (ruff, format,
  pyright, pytest with the 95% floor, notebooks, build, distribution). The owner decides on the
  snapshot (open question in the PR report).
- **Deviations:** (1) `edit` and `metadata_events` map no 401 code (the plan lists only 403, 404, 422
  and 403), so a 401 reports `scoreboard_contract_error`. (2) PATCH is sent with `replay_safe=True`
  (K5: idempotent by value). (3) Non-string `paper_url` raises `ValueError` (plan: "else
  ValueError"). (4) `LeaderboardScore.__post_init__` uses a new private `_optional_aware_datetime`
  helper because the extra branch broke the complexity lint.
