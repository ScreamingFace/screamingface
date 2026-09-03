---
ticket: OME-910
stack: repo
status: done
started: 2026-08-20
finished: 2026-08-20
---

# OME-910 — Repoint the git remote and release-critical org references

## Intent

The repo was transferred from the `OpenMined` org to `ScreamingFace`. GitHub keeps a
redirect, so nothing is broken yet — but the redirect is revocable, and PyPI Trusted
Publishing does not follow it: it matches the OIDC `repository` claim as an exact string.
Fix the local remote and the two in-repo references a redirect cannot cover, and surface the
PyPI-console change that only the owner can make.

## Planned changes

- `.git/config` — remote URL (untracked; already done, no branch).
- `packages/url4/pyproject.toml` — `Repository` / `Issues` project URLs (published PyPI metadata).
- `.github/workflows/release-url4.yml` — Trusted Publishing setup comment.
- `.github/workflows/release-screamingface.yml` — same.

Deliberately NOT touched: the ~130 remaining references in README/CONTRIBUTING/docs/
public-docs/portal (follow-up issue), the CHANGELOGs (correct when written),
and `OpenMined/sf-installer` (a genuinely different repo, still OpenMined-owned).

## Test plan

No code change — nothing to RED/GREEN. Verification is by inspection and by the repo's own
workflow linting:

- `git remote -v` resolves to the new URL and `git fetch` succeeds without redirect.
- No `OpenMined/screamingface` occurrence remains in the four in-scope files.
- `packages/url4` gates stay green (the pyproject edit must not break the build).

## Acceptance

- The four files above carry `ScreamingFace/screamingface`.
- `run_gates.py url4` green (pyproject is packaging metadata — the build must still work).
- The PyPI owner action is recorded on the issue, not silently assumed done.

## Outcome

- **Actual files:** as planned, plus an `AIDEV-NOTE` block added to both release workflows
  (see Deviations).
  - `.git/config` (untracked) — remote repointed; all five `.claude/worktrees/` entries AND
    `screamingface-demo-004` inherit it via `commondir`. `git fetch` verified over the new URL.
  - `packages/url4/pyproject.toml` — 2 occurrences.
  - `.github/workflows/release-url4.yml` — 1 + note.
  - `.github/workflows/release-screamingface.yml` — 1 + note.
- **Commits:** see below.
- **Gates:** `run_gates.py url4` — ALL GATES GREEN.
- **Deviations:**
  - `screamingface-demo-004` was assumed to be a separate clone needing its own `set-url`. It
    is a linked worktree of this clone, so it inherited the change — no action was needed.
  - Added an `AIDEV-NOTE (OME-910)` to both release workflows beyond the planned one-line
    swap. Correcting the comment does not repoint PyPI, and a reader could easily assume it
    does; the note states the failure mode explicitly so a release is not trusted on a stale
    publisher entry.
- **⚠️ OPEN — OWNER ACTION, not done by this change:** the PyPI Trusted Publisher entries for
  the `url4` and `screamingface` projects still name `OpenMined/screamingface`. Until an owner
  repoints them in the PyPI console, both release workflows build and verify green but fail at
  the publish step with an OIDC mismatch.
