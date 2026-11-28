---
ticket: OME-2041
stack: screamingface
status: done
started: 2026-11-26
finished: 2026-11-26
---

# OME-2041-client-author-website — accept a validated website + display_name per author in submit()

## Intent

`submit(..., authors_metadata=...)` already lets a caller stuff ANY key into one author's
metadata dict, sent through unvalidated. This unit gives `website` and `display_name` first-class
treatment in the client's own shape-check layer (`_scoreboard/credit_metadata.py`):

- `display_name` is accepted and mapped onto the already-known `full_name` key before the
  payload is built (sending both is refused — ambiguous which wins).
- `website` is validated as an absolute http(s) link — same shape rules as the existing
  `paper_url` validator in this package (`_scoreboard/leaderboards.py`'s `_paper_url`, itself
  mirroring the Scoreboard's `validate_paper_url` in
  `apps/scoreboard/src/scoreboard/scores/credit_metadata.py`): http/https only, a host, no user
  info, no control characters or whitespace, length capped at 2048 (matching the existing
  `_MAX_PAPER_URL_LENGTH`/`PAPER_URL_MAX_CHARS`).

This is the client-sf half of a cross-cutting pair (OME-2015 is the scoreboard-side sibling —
storage/API/portal rendering of the same fields). Independent, no ordering dependency; the
Scoreboard already accepts arbitrary `authors_metadata` keys today.

Out of scope (per ticket): account-level default profile (no server-side account concept yet).

## Planned changes

- `packages/screamingface/src/screamingface/_scoreboard/credit_metadata.py` — add
  `validate_author_website`; change `authors_metadata_value` to route each author's entry
  through a new `_author_profile` helper that maps `display_name`→`full_name` (refusing both)
  and validates `website` instead of treating it as an opaque scalar. `paper_metadata_value` is
  unchanged (the ticket scopes this to per-author metadata only).
- `packages/screamingface/tests/test_submission_author_profile.py` (new) — RED tests for the
  new behavior.

## Test plan

- `display_name` is sent as `full_name` on submit and edit.
- Sending both `display_name` and `full_name` for one author raises `ValueError` before any
  HTTP call, on both submit and edit.
- A valid `website` is sent through unchanged.
- A non-string `website` raises `TypeError`; a bad-shaped `website` (bad scheme, no host, user
  info, control char, whitespace, over the length cap) raises `ValueError` before any HTTP call,
  on both submit and edit — mirroring the existing `_REFUSED_LINKS` cases for `paper_url`.
- Existing `authors_metadata` shape tests (unknown key, non-mapping entry, non-string author
  key, `None` value) stay green unmodified — this change must not touch their behavior or
  error messages.

## Acceptance

- `submit()`/`edit()` accept `display_name` and `website` per author, validated client-side,
  with `display_name` landing in the payload as `full_name`.
- All prior `screamingface` package tests remain green and unmodified.
- `uv run .claude/scripts/run_gates.py screamingface` is green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** matches plan exactly —
  `packages/screamingface/src/screamingface/_scoreboard/credit_metadata.py` (added
  `validate_author_website`, `_author_profile`; `authors_metadata_value` routes through it;
  `paper_metadata_value` untouched) and
  `packages/screamingface/tests/test_submission_author_profile.py` (new, 13 tests).
- **Commits:** `5306f43a6` — feat(screamingface): validate an author's website and accept
  display_name in submit(); then the ledger and mirror commit.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface` — ALL GATES GREEN (append-only
  test check, ruff check, ruff format, pyright, pytest -n auto --cov=screamingface
  --cov-fail-under=95 (253 passed, prior suite + 13 new, all green and unmodified), node
  credit_refresh.test.mjs, check_notebooks.py, uv build, check_distribution.py).
- **Deviations:** none from the plan. One environment note: the local venv needed
  `uv sync --extra notebook` before `pyright`/the notebook gates would pass (matches
  `screamingface-tests.yml` CI, which runs the same sync step) — not a code change.
