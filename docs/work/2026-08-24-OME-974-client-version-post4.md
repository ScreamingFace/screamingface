---
ticket: OME-974
stack: py-screamingface
status: done
started: 2026-08-24
finished: 2026-08-24
---

# OME-974 — release the ScreamingFace client as 0.1.1.post4

## Intent

Publish the accumulated client work under `0.1.1.post4` without waiting on the release
automation, which has not refreshed since 2026-08-19.

## Planned changes

- `packages/screamingface/pyproject.toml` — `version` only, `0.1.1.post3` -> `0.1.1.post4`.
- `packages/screamingface/uv.lock` — regenerated so the lock agrees with the manifest.
- This ledger.

No source, test, or behaviour change.

## Test plan

- `uv lock --check` proves the lockfile matches the bumped manifest.
- `importlib.metadata.version("screamingface")` reports the new value from a fresh sync.
- The complete `screamingface` quality gate, since the package metadata is what CI builds from.

## Acceptance

- The installed client reports `0.1.1.post4`.
- Lockfile and manifest agree.
- Nothing outside those two files changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `packages/screamingface/pyproject.toml` and `packages/screamingface/uv.lock`,
  one line each, plus this ledger. No source, test, or behaviour change.
- **Verification:** `uv lock --check` clean; a fresh `uv sync --all-extras` reports
  `importlib.metadata.version("screamingface") == "0.1.1.post4"`.
- **Gates:** `run_gates.py screamingface` — append-only ✓ · ruff check ✓ · ruff format ✓ ·
  pyright ✓ · pytest --cov (95% floor) ✓ · notebook checks ✓ · `uv build` ✓ ·
  distribution checks ✓ — **ALL GREEN**.
- **Deviations:** the ticket was written against `0.1.1.post1`, read from a stale local `main`;
  `origin/main` already carried `0.1.1.post3`, so the real bump is post3 -> post4. The intended
  target version is unchanged. The first `sed` simply matched nothing and wrote nothing.
- **Follow-up (carried from the ticket):** `.release-please-manifest.json` still needs
  reconciling, or PR #592 refreshing, so the bot does not later recompute a version behind PyPI.
- **Commit:** `chore(screamingface): release the client as 0.1.1.post4`.
