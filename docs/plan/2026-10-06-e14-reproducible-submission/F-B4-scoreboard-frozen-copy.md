# F-B4 — scoreboard: frozen copy fields instead of cache version (rework of B4)

- **Worktree:** `.claude/worktrees/e14-b4-scoreboard-cache-version` · **Branch:** `e14-b4-scoreboard-cache-version`
  (rework in place, new commits on top) · **Base for gates:** `e14-a1-scoreboard-metadata` · **Stack:** `scoreboard`
- **Design:** `02-frozen-copy-design.md` §6 (binding). Rules: `00-common.md`.

## Changes

- Rename across `apps/scoreboard` (models, migration `0020`, schemas, store, routes, portal, this PR's own tests):
  - `cache_revision` → `frozen_copy_id`: a UUID string (36 chars, lowercase canonical form; validate with
    `uuid.UUID`, store `str(uuid)`), `CharField(36, null=True)`.
  - `reproducible` → `capture_status`: `Literal["complete", "partial"] | None`, `CharField(16, null=True)`.
  - `score_reproductions.cache_revision` → `frozen_copy_id`.
  - Rule I1: `frozen_copy_id` requires `capture_status`.
  - Fill-only rule unchanged (fill `frozen_copy_id` + `capture_status` together when `capture_status` is NULL;
    `answer_seed` fills alone).
  - Reproductions: 409 `not_reproducible` when `capture_status != "complete"`; 422 `not_exact` when `score`,
    `total_questions` or `frozen_copy_id` differ.
- Migration `0020_score_cache_version.py` is this PR's own, unreleased migration: rewrite it in place and rename
  the file to `0020_score_frozen_copy.py` (the stack is local; no deployed database has it). Keep
  `makemigrations` clean.
- Update docstrings, OpenAPI descriptions and the ledger. No behaviour change beyond the renames.

## Verify

`uv run .claude/scripts/run_gates.py scoreboard --base e14-a1-scoreboard-metadata`. The append-only check must
pass: only this PR's own tests change.
