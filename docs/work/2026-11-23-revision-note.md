---
ticket: OME-2001
stack: screamingface-engine, scoreboard
status: done
started: 2026-11-23
finished: 2026-11-23
---

# revision-note — show on each leaderboard why a Benchmark's revision changed

## Intent

A Benchmark's published revision moves when its Cases or grading change, and the leaderboard
shows the new revision as a bare hash. A reader cannot tell what changed or whether old scores
still compare. This unit adds a **revision note**: one plain-text line of at most 120
characters, written beside the revision id in the Engine, carried by the seed job to the
scoreboard, and shown under the revision selector for the selected revision.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py`: `Benchmark.revision_note`, validated, served present-only in the catalogue entry (the one seam both kinds of Benchmark pass through).
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`, `single_shot.py`: `BenchmarkSpec.revision_note` threaded to `Benchmark`.
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md`: the bump checklist names the note.
- `apps/scoreboard/src/scoreboard/seed.py`: `_CatalogEntry` and `SeedBenchmark` read the note.
- `apps/scoreboard/src/scoreboard/scores/store.py`, `scores/revisions.py`, `scores/models/benchmark_revision.py`, migration `0026`: store and return the note.
- `apps/scoreboard/portal/revision-selector.js`, `benchmark.js`, `benchmark.html`, `portal.css`: the line under the selector.
- New tests only; one token in `.claude/sdlc.local.md` and `.github/workflows/scoreboard-tests.yml` to register the new portal test file.

## Test plan

- Engine, extra-less: a declared note is served on `GET /v1/benchmarks`; an undeclared one adds no key; blank, over 120 characters and multi-line notes are refused at authoring time.
- Engine, inspect lane: every registered Benchmark's revision either predates notes (a frozen, digest-pinned set) or carries the note pinned for that exact id; a catalogue row's note reaches its Benchmark.
- Scoreboard: the catalogue reader keeps a usable note and drops an unusable one without losing the row; `record_revision` stores, replaces and keeps; the revisions route returns it; migration 0026 leaves existing rows NULL.
- Portal: the note line reads "first-seen date · note", nothing when empty, and is written as text.

## Acceptance

- A new revision's note reaches the Benchmark page; a revision without one shows what it shows today.
- A moved id without a note fails the Engine check before merge.
- No score, ranking or revision id changes.

## Decisions

- **A later deploy with different text for the same revision replaces the stored note; an absent note never erases one** (owner delegated). The Engine row is the author, so a typo fix reaches the page. Tradeoff: the board keeps no history of earlier wordings, and a note cannot be withdrawn by deleting it in the Engine (it has to be reworded).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `apps/scoreboard/portal/benchmark.html` and `portal.css` for the line itself. Migration number: `0026_benchmark_revision_note`.
- **Commits:** one commit on `OME-2001-revision-note`, `feat(scoreboard): show why a Benchmark's revision changed`.
- **Gates:** named test files only (owner rule; the full gates belong to CI). Engine: 112 passed in `tests/unit/test_benchmark_revision_note.py` and `tests/unit/inspect/test_revision_notes.py` with the inspect extra, and 235 more in the published-revision, re-grade, failure-policy and origin files beside them; extra-less, 27 passed and 1 skipped in the note and display-metadata files. Scoreboard: 20 passed in the two new files, 234 passed across the seed, revisions, migration and portal-markup files; 38 passed in the six revision portal test files. ruff and pyright clean on every touched Python file.
- **Deviations:**
  - The ticket's map named `screamingface_engine/rest/benchmarks.py` as the place that serves the note. The route is unchanged: it serves whatever `Benchmark.catalog_entry()` returns, so the note is added in `benchmarks/definition.py`, the one type both an imported row and a hand-built Benchmark become.
  - The check is a new file, `tests/unit/inspect/test_revision_notes.py`, not an edit to `test_published_revisions.py`, so no prior test changed and no approval file was needed.
  - An unusable note from the catalogue (over 120 characters, blank, more than one line, not text) is dropped, not cut: a cut note can lose the sentence that says whether scores compare. The Benchmark's row is kept (the `case_count` precedent).
  - `.claude/sdlc.local.md` and `.github/workflows/scoreboard-tests.yml` each gained one token, registering `tests/portal/revision-note.test.js` (owner-territory files; the same edit PR #2001 makes for its own portal test).
  - Not done: the SDK's local-stack seed twin (`packages/screamingface/src/screamingface/_runtime/bootstrap.py`) does not carry the note, so a local leaderboard shows none. That is a third landing and was not in this unit.

## Owner-verify

- Two deployments must land before a note shows: the Engine (serves the note), then the Scoreboard (migration 0026, then the seed job). No note exists yet, so nothing changes on any page until the first revision moves with one.
- Migration number: open PRs #2001 and #1981 each also add a `0026`. Whichever merges after another must renumber and re-point its `dependencies`.
- Open PRs #2003 (HealthBench Professional) and #1999 (MedXpertQA) each move a revision. Whichever merges after this one must declare `revision_note=` and add its line to `_NOTED_REVISIONS`; the new check goes red until it does.
- Visual: checked on a throwaway local scoreboard in light and dark and at 400 px wide. Worth one look on dev after the first noted revision deploys.
