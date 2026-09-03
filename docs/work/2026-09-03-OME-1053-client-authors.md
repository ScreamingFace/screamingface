---
ticket: OME-1053
stack: screamingface
status: done
started: 2026-09-03
finished: 2026-09-03
---

# OME-1053 — Add co-author emails to client submissions

## Intent

Allow Python users to credit every collaborator on a leaderboard submission while keeping
submission ownership separate from authorship. The client sends the exact author email list to
the Scoreboard and exposes the Scoreboard's privacy-trimmed author identifiers on returned score
and leaderboard values.

## Planned changes

- Add the approved client contract in `docs/spec/2026-09-03-OME-1053-client-authors.md` and its
  implementation plan in `docs/plan/2026-09-03-OME-1053-client-authors.md`.
- Add the required issue mirror in
  `docs/tasks/2026-09-03-OME-1053-add-co-author-emails-to-client-submissions.md`.
- Extend the lazy, synchronous, and asynchronous leaderboard submission APIs in
  `packages/screamingface/src/screamingface/leaderboards.py` and
  `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py`.
- Add immutable author data to `packages/screamingface/src/screamingface/leaderboard.py` and
  decode it from Scoreboard score and leaderboard responses.
- Document the public call and read behavior in `packages/screamingface/README.md`.
- Add append-only behavior and contract coverage in
  `packages/screamingface/tests/test_leaderboards.py`, refresh the public API snapshot, and record
  the public feature in `packages/screamingface/CHANGELOG.md`.

## Test plan

- RED: prove lazy, sync, and async APIs forward the exact author list and never auto-add the
  submitter.
- RED: prove omitted authors stay omitted and invalid local author inputs fail before HTTP.
- RED: prove score and leaderboard responses expose immutable privacy-trimmed authors and reject
  malformed author arrays.
- GREEN: run the focused tests, full package suite, coverage, lint, format, typecheck, notebook,
  build, and distribution gates.

## Acceptance

- `sf.leaderboards.submit(result, authors=[...])`, sync Client, and AsyncClient all send the same
  top-level `authors` array.
- `authors=None` sends no field; an explicit list is exact and never expanded with the submitter.
- Author input is a non-empty collection of at most ten syntactically valid email strings, each
  at most 255 characters.
- `LeaderboardScore.authors` and `LeaderboardEntry.authors` expose immutable values decoded from
  the new Scoreboard contract.
- All ScreamingFace package quality gates pass and a draft PR identifies the Scoreboard rollout
  dependency.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** all planned implementation, test, snapshot, changelog, README, spec, plan,
  task-mirror, and ledger files.
- **Commits:** `feat(screamingface): support leaderboard co-authors` (one squash-ready commit on
  `OME-1053-client-authors`; sha recorded in the draft PR).
- **Gates:** 16 author-focused tests passed; the complete
  `python3 .claude/scripts/run_gates.py screamingface --skip-append-only` suite passed twice:
  ruff check, ruff format check, pyright (0 errors), pytest with at least 95% coverage,
  deterministic notebook validation, wheel build, and distribution validation.
- **Deviations:** The public-surface snapshot is an existing test artifact and changed because the
  owner explicitly approved the new public `authors=` signature and returned `authors` fields.
  The snapshot's own regeneration workflow passed; the gate runner's append-only precheck was
  skipped only for that authorized mechanical snapshot update. All test behavior was added
  append-only. Read support was included in this unit by owner decision so the SDK does not
  silently discard the Scoreboard's new response field.
