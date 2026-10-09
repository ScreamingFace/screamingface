---
ticket: OME-1436
stack: screamingface
status: done
started: 2026-10-06
finished: 2026-10-06
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

## Approved test changes (append-only exception)

**Owner approval:** confirmed by the owner on 2026-10-08. The append-only gate may skip these edits.

- `tests/public_surface_snapshot.json` regenerated with `UPDATE_SURFACE_SNAPSHOT=1` for the new
  public names (`edit`, `metadata_events`, `ScoreMetadataEvent`, `paper_url`,
  `metadata_updated_at`). Orchestrator-approved under the owner's E14 authorization, to be
  confirmed by the owner.

## Further coordinator answers (2026-10-06)

- 401 on `edit` and `metadata_events` maps to `scoreboard_authentication_required`, as `submit`
  does, through `_status_code`.
- A `paper_url` that is not a `str` raises `TypeError`; a bad value (scheme, length) raises
  `ValueError`. Deviations on `replay_safe=True`, the `_optional_aware_datetime` helper and the
  `_Unset` signature repr are accepted.

## Design-review fixes (coordinator, 2026-10-06; one round, new tests only)

- `_paper_url` mirrors the board's `_validate_paper_url`: also control characters, any whitespace,
  no host, user info (including a bare `@`); the scheme check is case-insensitive.
- `_error_details` unwraps a `{code, message}` detail to `code: message` (new private
  `_detail_text`); a flat string and any other shape are unchanged, so submit errors keep their
  shape (regression test).
- PATCH 409 maps to `score_edit_conflict`, `permanent=False`, hint "Retry the edit." through the
  new `_CONFLICT_HINTS` table, which also holds the submit hint.
- `_SUBMIT_OPERATION` replaces the repeated submit operation string.
- Note at the `_decode_authors` call in `_decode_metadata_event` (events carry full addresses).
- README "Discovery": `paper_url`, `edit`, `metadata_events`. README is not in the plan's file list;
  the coordinator asked for it.
- Left as instructed: review items 6, 7 and 9.

## Test plan

- PRD TDD #19: `submit` sends `paper_url` only when given; client-side check (http/https, 1-2048).
- PRD TDD #20: `edit` sends PATCH and decodes the score (sync and async); argument rules.
- PRD TDD #21: `edit` maps 403, 404, 422 to typed errors; events 403.
- PRD TDD #22: `metadata_events` decodes the list; empty list; older board omits the new fields.

## Acceptance

- Gates for stack `screamingface` pass against base `e14-reproducible-submission-spec`.
- No existing test edited or removed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and `packages/screamingface/README.md` (asked for
  by the coordinator in the design review).
- **Commits:** see `git log --oneline e14-reproducible-submission-spec..HEAD`.
- **Gates:** see the final run in the PR report. Without `--skip-append-only` the run stops at the
  approved snapshot exception above; with it, all other gates are green.
- **Deviations:** `replay_safe=True` on PATCH; private `_optional_aware_datetime` helper (the extra
  branch broke the complexity lint); `_Unset` and `UNSET` appear in the public signatures. All
  accepted by the coordinator.
