# B4 — scoreboard: cache version and reproductions

- **Worktree:** `.claude/worktrees/e14-b4-scoreboard-cache-version` · **Branch:** `e14-b4-scoreboard-cache-version`
- **Base:** `e14-a1-scoreboard-metadata` (A1 must be accepted first; this PR reuses its
  `VerifiedIdentity` and follows migration `0019`) · **Stack:** `scoreboard`
- **PRDs:** `prd/cache-version-capture.md` (C4, C10, C12; TDD #16–#18) and `prd/reproduce.md`
  (R4, R6, R12–R15, R18, R22; TDD #7–#14). Contracts K4, K7, K8. ERD §1, §3, §6. Rules: `00-common.md`.

## Files

| File | Change |
|---|---|
| `src/scoreboard/scores/migrations/0020_score_cache_version.py` | `AddField` `cache_revision` (`CharField(32, null=True)`), `reproducible` (`CharField(16, null=True)`), `answer_seed` (`IntField(null=True)`); `CreateModel` `ScoreReproduction` |
| `src/scoreboard/scores/models/score.py` | the three fields |
| `src/scoreboard/scores/models/score_reproduction.py` | new model (export like A1's event model) |
| `src/scoreboard/scores/schemas.py` | the three fields on `ScoreSubmission` and `ScoreSchema`; `reproduction_count: int = 0`, `last_reproduced_at: datetime \| None` on `ScoreSchema`; `ReproductionSubmission`, `ReproductionSchema` |
| `src/scoreboard/scores/store.py` | fill-only rule in `_replay_updates` for the three fields (+ `_REPLAY_FIELDS`, not enriching); `ScoreStore.record_reproduction(...)`; reproduction aggregate for the score read |
| `src/scoreboard/routes/scores.py` | `POST /v1/scores/{score_id}/reproductions`; `GET` adds the aggregate |
| `portal/spec.js` | "Reproduced N times · last <date>" when `reproduction_count > 0` |
| tests | new files only; a new portal test file must be added by name to the `node --test` gate line in `.claude/sdlc.local.md` |

Exemplars: A1's `ScoreMetadataEvent` model + migration + `VerifiedIdentity` routes;
`_replay_updates` fill-only blocks for `models` and cost (`store.py`).

## Decisions (pinned)

- Validation on `ScoreSubmission`: `reproducible: Literal["complete", "partial"] | None`;
  `cache_revision: str | None` matching `^cr-[0-9a-f]{12}$`; `cache_revision` without
  `reproducible` → 422 (I1); `answer_seed: int | None` (any int that fits a 32-bit signed INT; else 422).
- None of the three enter `_content_hash`.
- Fill-only: a resubmit sets a field only when the stored value is NULL; a different non-NULL value
  is kept, not replaced (C12). `cache_revision` and `reproducible` move together: fill both only
  when `reproducible` is NULL on the row.
- `ScoreReproduction`: `id` UUID pk; `score` FK → `models.Score` (`related_name="reproductions"`,
  `on_delete=CASCADE`); `reproduced_by CharField(255)`; `reproduced_at DatetimeField(auto_now_add=True)`;
  `run_id CharField(128)`; `cache_revision CharField(32, null=True)`; `client_version CharField(64, null=True)`.
  `unique_together = (("score", "run_id"),)`. Table `score_reproductions`.
- `ReproductionSubmission` (`extra="forbid"`): `run_id: str` (1–128), `score: float`,
  `total_questions: int`, `cache_revision: str | None` (same pattern), `client: ClientInfo`
  (reuse the existing `ClientInfo`).
- `POST /v1/scores/{score_id}/reproductions` check order: `VerifiedIdentity` (401/403) → score
  exists (404) → private board and caller ≠ owner → 404 → `score.reproducible != "complete"` →
  409 `{"code": "not_reproducible", …}` → `score`, `total_questions` or `cache_revision` differ from
  the row → 422 `{"code": "not_exact", …}` (exact float equality, the same value the board stores) →
  insert. An existing `(score_id, run_id)` → 200 with that row (insert, and on `IntegrityError`
  re-read; do not pre-check then insert without handling the race). New → 201.
- No cap on rows per identity (ans:Q9).
- `reproduction_count` / `last_reproduced_at`: one aggregate query (`COUNT`, `MAX(reproduced_at)`)
  when building the `GET /v1/scores/{id}` response. Do not add them to the leaderboard rows.

## Do not

- Do not record failed replays. Do not add a per-identity limit. Do not change ranking.

## Verify

`python3 .claude/scripts/run_gates.py scoreboard --base e14-a1-scoreboard-metadata`
