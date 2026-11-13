---
ticket: OME-1906
stack: screamingface-engine
status: done
started: 2026-11-13
finished: 2026-11-13
---

# answer-format-rest — the answer-format sentence for the other 60 rows (PR 2 of 2)

## Intent

PR 1 of 2 (#1780) appends one answer-format sentence per scorer to the 35 rows graded by
inspect's `choice`. This unit covers the other 60 rows (37 scorers) and medxpert, and adds the
closing invariant: every catalogue row publishes a sentence, so a new Benchmark cannot ship
without one. Every non-judge sentence's quoted replies are graded through each row's real
grader on a stand-in Case; a judge-graded sentence quotes no graded replies (grading them is
a paid judge call) and says that a judge reads the reply.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/answer_formats.py` → package
  `answer_formats/` (`__init__` merge + lookup, `_format.py` the dataclass, one file per scorer
  family: `_choice.py`, `_letters.py`, `_exact.py`, `_judged.py`), so entries stay grouped by
  how the grader reads and an entry can be keyed by row when one scorer is configured per row
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — lookup by row key and scorer
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/definition.py` — its sentence
- `apps/screamingface-engine/tests/unit/inspect/test_answer_formats.py` (added in PR 1 of 2, same ticket and stack)
- `apps/screamingface-engine/CHANGELOG.md`, the mirror

## Test plan

- Every catalogue row publishes its prose followed by its sentence (no row left out).
- Every quoted reply of every non-judge entry grades as stated through every row it serves.
- A judge-graded entry quotes no graded replies and names the judge; a row has a judge iff its entry is judge-graded.
- No key is defined in two family files.

## Acceptance

- `/v1/benchmarks` serves a sentence for all 95 rows and medxpert; fingerprint and published-revision tests pass unedited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `answer_formats/_letters.py` (21 rows), `_exact.py` (18 rows), `_judged.py` (21 rows), `answer_formats/__init__.py` (merges the four families), medxpert `definition.py` (its sentence as `ANSWER_FORMAT`), new tests `test_answer_formats_every_row.py` and `test_medxpert_answer_format.py`, `CHANGELOG.md`, the mirror (closed) and this ledger. The package shape, the per-row key and the stand-in Case per rule moved into PR 1 of 2 (`488f20838`) before any prior test existed on main, so this PR edits no prior test.
- **Commits:** the PR 2 of 2 commit on `OME-1906-pr2-answer-format-rest`.
- **Gates:** with the inspect extra, the answer-format, every-row, medxpert, fingerprint, published-revision, imported-Benchmark and scorer-pin test files: 1068 passed. ruff check, ruff format and pyright clean on the touched files. Mutation check: marking mathvista's 'ANSWER: 12.0' as accepted turns the grading test red; the medxpert test caught a false example on the first run ('I am not sure' reads the pronoun I as option I), so it became 'not sure'.
- **Deviations:** the rules were written by three parallel agents, one per family file, each graded through the rows' real grader; reviewed by hand: the bbh sentence said 'exactly' where the rule forgives bold, backticks and a final period, now said. Sentence parts no stand-in reply exercises (bbh's yes/no and free-form halves, mathvista's multiple-choice half, AIME's cut-off clause, partial-credit wording on squad, drop and musique) are true from the code but not graded in a test. arc_agi_2's stand-in carries no metadata: shared task ids made its per-task metric return 2.0, and the scorer reads none. Review round 1: lab_bench's sentence said any mark around the letter scores 0, as #1780's did; inspect's fallback pattern accepts a non-word character after it, so both now name only marks between `ANSWER:` and the letter and quote `ANSWER: B.` as accepted. medxpert's sentence said the grader takes the last letter; it reads an explicit 'the answer is D' first (`extract_letter` returns D for 'the answer is D. B would be wrong.'), now said and graded. The every-row test covers imported rows only; a hand-built core Benchmark is pinned by its own test, so the claim is narrowed to imported rows. 'Rule' became 'answer format' in names and docstrings.
