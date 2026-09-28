---
ticket: OME-1150
stack: screamingface-engine
status: done
started: 2026-09-09
finished: 2026-09-09
---

# OME-1150 — Type the grading spine's local variables and land the rescued candidate-fields dataclass

## Intent

PR #847 merged an older tip of its branch: a follow-up commit fixing a real type lie
(`scored_case_result` declared `output: str` but receives `None` for no-answer rows) and
replacing the candidate-fields dict with a frozen dataclass existed only on the local
branch after the remote was auto-deleted. This unit lands that commit and finishes the
job: every non-trivial local in the spine gets an inline annotation, so the seam the
draco fold-in (OME-1099) and the inspect adapter build on states its own types.

## Planned changes

- Cherry-pick `26ed5ce5` (done, now `70fd787e`): `CandidateFields` dataclass, honest
  `str | None` output, spine docstring walkthroughs.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/spine/exam.py` — annotate locals.
- `.../spine/rows.py` — annotate locals.
- `.../spine/scored.py` — annotate remaining locals.
- `.../spine/rubric.py` — annotate remaining locals; restore the module docstring's one-line title.
- `.../spine/scored.py` — mend the stage-list formatting drift in the module docstring.

## Test plan

- No behavior change intended: existing spine/benchmark test suite must stay green,
  pyright must stay clean. No new tests — annotations only; the dataclass commit was
  already reviewed on the merged PR's seam.

## Acceptance

- `26ed5ce5` content is on the branch; annotations cover every non-trivial local
  (RHS = call / comprehension / `.get()` / conditional) in the four spine modules.
- `uv run pytest`, `uv run ruff check`, `uv run pyright` green in
  `apps/screamingface-engine`.
- PR open, `Refs: OME-1150`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `exam.py`, `rows.py`, `scored.py`, `rubric.py` (annotations
  + both docstring nits), plus the cherry-picked dataclass commit.
- **Commits:** `70fd787e` — refactor(screamingface-engine): type the candidate row fields and
  teach the spine docstrings (cherry-pick of orphaned `26ed5ce5`); annotation commit follows.
- **Gates:** pyright 0 errors · ruff clean · pytest 2646 passed, 8 skipped, 1 failed
  (`test_worker_child_memory_cap` — pre-existing, fails identically on clean main; local
  macOS environment, unrelated to this change).
- **Deviations:** `read_selected_cases`' `by_id` comprehension now binds the id once via a
  walrus (`row_id`) so the declared `dict[int, …]` type checks — same filter semantics, one
  fewer repeated `.get()`.
