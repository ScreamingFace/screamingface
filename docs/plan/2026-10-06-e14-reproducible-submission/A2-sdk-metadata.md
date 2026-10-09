# A2 — SDK: paper link, edit, metadata events

- **Worktree:** `.claude/worktrees/e14-a2-sdk-metadata` · **Branch:** `e14-a2-sdk-metadata`
- **Base:** `e14-reproducible-submission-spec` · **Stack:** `screamingface`
- **PRD:** `prd/metadata-ownership.md` (M1, M5, M6, M8, M10; TDD #19–#22). Contracts K4, K5, K6, K8.
  Rules: `00-common.md`.
- The scoreboard half (A1) is built in parallel. Code against the contract in `contracts.md`; fake
  the HTTP with `httpx.MockTransport`.

## Files

| File | Change |
|---|---|
| `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` | `submit(..., paper_url=None)`; new `edit(...)` and `metadata_events(...)` on `Leaderboards` and `AsyncLeaderboards`; `_decode_score` reads the new fields; `_decode_metadata_event` |
| `packages/screamingface/src/screamingface/leaderboards.py` | module-level `edit` and `metadata_events` wrappers; add to `__all__` |
| `packages/screamingface/src/screamingface/leaderboard.py` | `LeaderboardScore.paper_url: str \| None = None`, `metadata_updated_at: datetime \| None = None`; new frozen dataclass `ScoreMetadataEvent` |
| `packages/screamingface/src/screamingface/__init__.py` | export `ScoreMetadataEvent` |
| `packages/screamingface/tests/public_surface_snapshot.json` | regenerate with `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py` (this is the documented update path, not a test edit) |
| `packages/screamingface/tests/test_leaderboards_metadata.py` | new (append-only) |

Exemplars: `submit` / `get_score` and `_decode_score` in `_scoreboard/leaderboards.py`;
`LeaderboardScore` validation style in `leaderboard.py`; `tests/test_leaderboards.py` helpers
(`_sync_client`, `_async_client`, `_score_response`, `_candidate_result`).

## Decisions (pinned)

- `submit(candidate_result, *, authors=None, paper_url=None)`. Client-side check of `paper_url`:
  `str`, `http`/`https`, 1–2048 characters, else `ValueError`. Send `"paper_url"` only when not None.
- `edit(score_id: UUID | str, *, authors: Sequence[str] | None | _Unset = UNSET, paper_url: str | None | _Unset = UNSET) -> LeaderboardScore`.
  Use a module-private sentinel (`_UNSET = object()` with a typed `_Unset` class, or the pattern
  the package already uses for "not given", if one exists; search first). Rules: no argument given →
  `ValueError`; `authors=None` → `ValueError` (the board refuses it); `paper_url=None` → sends
  `"paper_url": null` (clears). Authors go through `_submission_authors`. Sends
  `PATCH /v1/scores/{id}` and decodes the body with `_decode_score`.
- `metadata_events(score_id) -> tuple[ScoreMetadataEvent, ...]`: `GET /v1/scores/{id}/metadata-events`.
- `ScoreMetadataEvent` fields: `id: UUID`, `edited_by: str`, `edited_at: datetime` (aware),
  `source: Literal["patch", "resubmit"]`, `old_authors: tuple[str, ...] | None`,
  `new_authors: tuple[str, ...] | None`, `old_paper_url: str | None`, `new_paper_url: str | None`.
- Errors: reuse `_response_json` / `_status_code`. Add operation-specific codes the same way the
  existing ones are added: PATCH 403 → `"score_edit_forbidden"`, 404 → the `missing` tuple
  (`"score_not_found"`, as `get_score` uses), 422 → `"invalid_score_edit"`; events 403 →
  `"score_events_forbidden"`. Look at how `_status_code(status, operation)` keys by operation and
  extend it; do not add a parallel mapper.
- An older board omits the new fields → decode as `None`.

## Do not

- Do not edit `CHANGELOG` files (release-please writes them).
- Do not add retry logic. Do not touch the engine transport.

## Verify

`cd packages/screamingface && uv sync --extra runtime --extra notebook`, then
`python3 .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec`
