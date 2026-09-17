---
ticket: OME-525
stack: repo
status: done
started: 2026-07-21
finished: 2026-07-21
---

# OME-525 — pre-commit framework + fix stale core.hooksPath

## Intent
Introduce the pre-commit framework (first in the monorepo) and fix the stale local
`core.hooksPath` (currently `apps/desktop/.husky/_`, a removed legacy path) so the committed
`.githooks/` fire. Fast hooks (ruff-check / ruff-format / std) gate every commit; the heavy
per-stack `run_gates.py` runs on pre-push + CI. Prerequisite for OME-514 (url4-cloud scaffold).

## Planned changes
- `.pre-commit-config.yaml` (repo root) — fast hooks.
- `.githooks/pre-commit` — keep the no-commit-to-main guard, then `pre-commit run`.
- `.githooks/pre-push` — `run_gates.py` for the changed stacks.
- Local `git config core.hooksPath .githooks` (+ documented in the ledger; committed hooks only).
- `docs/tasks/2026-07-21-precommit-hookspath.md` (mirror).

## Test plan
- `.pre-commit-config.yaml` is valid + hooks resolve: `uvx pre-commit run --all-files` completes
  (auto-fixes applied, then clean).
- The no-commit-to-main guard still rejects a commit on `main`.
- On a feature branch, `.githooks/pre-commit` invokes pre-commit.

## Acceptance
- pre-commit config committed; `.githooks/{pre-commit,pre-push}` updated; `core.hooksPath` fixed;
  hooks fire on this branch.

## Outcome (fill at the end — required before COMMIT)
- **Actual files:** `.pre-commit-config.yaml`, `.githooks/pre-commit` (extended), `.githooks/pre-push`
  (new), this ledger, `docs/tasks/2026-07-21-precommit-hookspath.md`.
- **Commits:** see the OME-525 commit on `OME-513-url4-cloud`.
- **Gates:** `pre-commit validate-config` PASS; `pre-commit run` on the staged set PASS
  (trailing-whitespace · end-of-file · check-yaml · large-files · merge-conflict; toml/ruff skipped
  — no matching files) with no auto-edits; `core.hooksPath` fixed `apps/desktop/.husky/_` → `.githooks`;
  hooks executable and firing (this commit runs them).
- **Deviations:** pyright/pytest/coverage intentionally deferred to **pre-push** (not per-commit) to
  keep commits fast; did **not** run `pre-commit run --all-files` (it would reformat the whole
  existing repo — recommend a separate normalization change); `ruff-pre-commit` pinned to `v0.14.0`
  (re-pin via `pre-commit autoupdate` when network allows).
