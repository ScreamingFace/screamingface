---
ticket: OME-1908
stack: screamingface-engine
status: done
started: 2026-11-13
finished: 2026-11-13
---

# drop-midrun-check-sentence — a Benchmark page mentions Draft Feedback only when it offers it

## Intent

76 of the 96 Benchmark pages end with a sentence about the mid-run check ("No mid-run check
surface (elimination attack over options)."), while ifeval, the one Benchmark that offers Draft
Feedback, says nothing. Not offering it is the default, so the 71 "No …" sentences are noise to
a submitter; the 4 "Free-form replies make the mid-run check surface legitimate (corrective
loop)" sentences (paws, boolq, aime24, aime25) read as if a Corrective Loop runs there, which
the client refuses, and paws and boolq answer Yes/No, where pass/fail feedback is the
elimination attack. Remove the sentence from all 76 and state the offer on ifeval's page. The
description is not part of the revision, so no published revision or fingerprint moves.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — drop the sentence
  from 76 descriptions; add one sentence to ifeval's
- `apps/screamingface-engine/tests/unit/inspect/test_draft_feedback_on_page.py` — new
- `apps/screamingface-engine/CHANGELOG.md`, the mirror in `docs/tasks/`

## Test plan

- A page mentions Draft Feedback (or the mid-run check, the check surface, the elimination
  attack, a corrective loop) exactly when its Benchmark offers Draft Feedback: red on main for
  76 rows and for ifeval, green after.
- ifeval's page names Draft Feedback.

## Acceptance

- The scan of all 96 assembled descriptions plus medxpert finds the mention on ifeval only;
  fingerprint and published-revision tests pass unedited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `benchmarks.py` (76 descriptions lose the sentence, ifeval's gains one), the new `test_draft_feedback_on_page.py`, `CHANGELOG.md`, the mirror and this ledger.
- **Commits:** the one commit on `OME-1908-drop-midrun-check-sentence`.
- **Gates:** with the inspect extra, the new test file plus the fingerprint, published-revision, imported-Benchmark, provenance, Task-replay assembly, scorer Draft Feedback, local ifeval and owner opt-in files: 986 passed; extra-less, `test_benchmark_display_metadata.py` 19 passed. On main the new test fails for the 76 rows and ifeval (78 failed). ruff check, ruff format and pyright clean on the touched files.
- **Deviations:** none from the plan. The 76 edits were made by a script that keeps every string fragment before the cut byte-for-byte and rewraps only the tail; a comparison of old and new descriptions confirmed each new text is the old one with exactly the sentence removed (14 distinct wordings), and no non-string line changed.
