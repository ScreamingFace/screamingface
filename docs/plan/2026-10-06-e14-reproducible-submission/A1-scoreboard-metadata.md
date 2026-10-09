# A1 — scoreboard: paper link, edit, edit log

- **Worktree:** `.claude/worktrees/e14-a1-scoreboard-metadata` · **Branch:** `e14-a1-scoreboard-metadata`
- **Base:** `e14-reproducible-submission-spec` · **Stack:** `scoreboard`
- **PRD:** `prd/metadata-ownership.md` (scenarios M1–M21, TDD #1–#18). Rules: `00-common.md`.

## Files

| File | Change |
|---|---|
| `apps/scoreboard/src/scoreboard/scores/migrations/0019_score_metadata.py` | new: `AddField` `paper_url` (`TextField(null=True)`), `AddField` `metadata_updated_at` (`DatetimeField(null=True)`), `CreateModel` `ScoreMetadataEvent` |
| `apps/scoreboard/src/scoreboard/scores/models/score.py` | `paper_url`, `metadata_updated_at` |
| `apps/scoreboard/src/scoreboard/scores/models/score_metadata_event.py` | new model (export it where the other models are exported, e.g. `models/__init__.py`) |
| `apps/scoreboard/src/scoreboard/scores/schemas.py` | `PaperUrl` type; `paper_url` on `ScoreSubmission` and `ScoreSchema`; `metadata_updated_at` on `ScoreSchema`; `ScoreMetadataPatch`; `ScoreMetadataEventSchema` |
| `apps/scoreboard/src/scoreboard/scores/store.py` | `paper_url` in `_REPLAY_FIELDS` + `_replay_updates`; event write in `_apply_replay_updates`; new `ScoreStore.patch_metadata(...)` and `ScoreStore.metadata_events(...)` |
| `apps/scoreboard/src/scoreboard/routes/dependencies.py` | `verified_identity()` + `VerifiedIdentity` |
| `apps/scoreboard/src/scoreboard/routes/scores.py` | `_resolve_submitter` delegates the header/peer logic to the shared helper; `PATCH /v1/scores/{score_id}`; `GET /v1/scores/{score_id}/metadata-events` |
| `apps/scoreboard/portal/spec.js` (+ `main.js` only if a helper is needed) | show the paper link in the history row / detail |
| `apps/scoreboard/tests/unit/…` | new test files (append-only): `test_score_paper_url.py`, `test_score_metadata_patch.py`, `test_score_metadata_events.py` |
| `apps/scoreboard/tests/portal/paper-link.test.js` | new; **add it by name** to the `node --test` gate line in `.claude/sdlc.local.md` (that file edit is allowed) |

Exemplars: migration `0017_score_cache_saved_cost_archive.py` (AddField) and `0001_initial.py`
(`CreateModel` shape, but use the native FK, see `00-common.md`); route tests
`tests/unit/test_scores_routes.py` (`app_with_cloudflare_auth` fixture, `X-User-Email` header).

## Decisions (pinned)

- `PaperUrl`: `str`, 1–2048 characters, scheme `http` or `https` (case-insensitive), no ASCII
  control characters, has a host. Validate with `urllib.parse.urlsplit`. Do not use pydantic
  `HttpUrl` (it normalizes the string; store the string as sent).
- `ScoreMetadataEvent` fields: `id` UUID pk, `score` FK → `models.Score` (`related_name="metadata_events"`,
  `on_delete=CASCADE`), `edited_by` `CharField(255)`, `edited_at` `DatetimeField(auto_now_add=True)`,
  `source` `CharField(16)` (`"patch"` | `"resubmit"`), `old_authors` / `new_authors` `JSONField(null=True)`,
  `old_paper_url` / `new_paper_url` `TextField(null=True)`. Table `score_metadata_events`. Index
  `(score_id, edited_at)`.
- `verified_identity(request) -> str`: in `cloudflare_headers` mode, the same peer check and header
  read as `_resolve_submitter` (403 untrusted peer, 401 missing identity); in `disabled` mode,
  read `X-User-Email` and 401 if absent. `_resolve_submitter` keeps its disabled-mode body fallback.
  Move the shared header/peer code into one private helper so both use it (the AIDEV-NOTE at
  `scores.py:101`).
- `ScoreMetadataPatch` (`extra="forbid"`): `authors: list[AuthorEmail] | None` (reuse the
  same validation as `ScoreSubmission.authors`, min 1, max 10 distinct, 4096 bytes) and
  `paper_url: PaperUrl | None`. Use `model_fields_set` to tell "absent" from `null`. Rules: at least
  one key present (else 422); `authors` present with `null` → 422; `paper_url: null` clears.
- `PATCH /v1/scores/{score_id}` → 200 `ScoreSchema`. Order of checks: identity (401/403) → score
  exists (404) → private board and not owner → 404 → not owner → 403
  `{"code": "not_score_owner", "message": …}` → apply. Apply inside
  `in_transaction(connection_name=DEFAULT_CONNECTION)`, re-read the row with `select_for_update()`
  (call it LAST, see `replay_row_query`), compute changes, and if any: update the row (set
  `metadata_updated_at = now(UTC)`) and insert one event. No change → no write.
- Resubmit: in `_apply_replay_updates`, when `authors` or `paper_url` change against the locked row,
  insert one event with `source="resubmit"` and set `metadata_updated_at` in the same update. Keep
  `authors`/`paper_url` out of `_ENRICHING_FIELDS`.
- `GET /v1/scores/{score_id}/metadata-events` → 200 `list[ScoreMetadataEventSchema]`, newest first.
  Owner only: not owner → 403 (404 on a private board). Add `Cache-Control: private, no-store`
  (`PRIVATE_CACHE_HEADERS`).
- `paper_url` never enters `_content_hash`.
- Add both new routes to the `responses=` dict pattern (`GET_SCORE_RESPONSES` style).

## Do not

- Do not add an admin route. Do not add ETag/If-Match. Do not change ranking, `enriched_at` or the
  leaderboard row shape.

## Verify

`python3 .claude/scripts/run_gates.py scoreboard --base e14-reproducible-submission-spec`
