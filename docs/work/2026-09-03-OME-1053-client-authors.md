---
ticket: OME-1053
stack: screamingface
status: in_review
started: 2026-09-03
finished: 2026-09-04
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

## Review follow-up — 2026-09-04

### Intent

Close the validated PR review findings before marking the client authorship change ready: keep
write validation aligned with Scoreboard while making reads forward-compatible, present authorship
honestly in the receipt and public docs, and classify Scoreboard conflicts with the retry remedy
the server promises.

### Planned changes

- Add regression tests for accepted write boundaries, uncapped and exact read values, retryable
  submission conflicts, and separate submitter/authors receipt fields.
- Remove the write-only author cap and normalization from read models while retaining structural
  response validation.
- Render separate submitter and authors values in the notebook receipt.
- Treat Scoreboard submission conflicts as retryable with a stable client error code and hint.
- Remove the manual release-please changelog entry and update both public leaderboard docs pages.

### Test plan

- RED: run the new focused ScreamingFace tests and confirm each review regression fails for its
  intended reason.
- GREEN: run the full ScreamingFace gate runner.
- Run the public-docs lint, typecheck, and production build gates.

### Acceptance

- Exactly ten authors and a 255-character address are accepted on writes; the existing rejected
  boundaries remain rejected.
- Reads accept more than ten nonblank authors and preserve each string byte-for-byte.
- The receipt labels and displays both submitter and authors without changing SFDS styling.
- Submission HTTP 409 raises a retryable `LeaderboardError` with a conflict-specific remedy.
- Release automation owns the changelog entry and deployed public docs describe the new API.

### Outcome

- **Actual files:** updated the Scoreboard adapter, public leaderboard models, notebook receipt,
  leaderboard tests, and both public-docs leaderboard pages; removed the hand-written changelog
  entry so release-please remains the sole owner of release notes.
- **RED/GREEN:** the focused review suite first failed in the four intended areas (conflict
  classification, read cap, exact read text, and receipt fields), then passed with 21 tests.
  The complete package suite passed with 1,334 tests and 22 skips.
- **Package gates:** the canonical ScreamingFace gate runner passed ruff check and format, pyright,
  pytest with the 95% coverage floor, notebook validation, wheel build, and distribution checks.
- **Public-docs gates:** Prettier, oxlint, ESLint, Vue typechecking, and the production Vite build
  passed.
- **Deviation:** one test added by the original OME-1053 commit treated eleven returned authors as
  malformed. The approved review correction removed that write-only limit from the read contract,
  so that parameter was replaced with positive forward-compatibility coverage. The append-only
  precheck was skipped for this authorized correction; all other package gates ran unchanged.
- **Scope:** diagnostics findings raised during the follow-up were verified as absent from PR #830
  and were not mixed into this unit of work.
