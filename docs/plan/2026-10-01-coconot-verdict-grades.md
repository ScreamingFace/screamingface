# Plan — coconot, graded by its judge's words

- Spec: `docs/spec/2026-10-01-coconot-verdict-grades.md`. Ledger:
  `docs/work/2026-10-01-coconot-import.md`. Ticket: OME-1371.
- Root for paths below: `apps/screamingface-engine/`. One PR.

## Steps

1. **Failing tests first** (`tests/unit/inspect/test_verdict_grades.py`) → verify: red for the
   missing field, not for a typo.
2. **Scorer adapter grades by the map** (`scorer_adapter.py`): `inspect_grade_case(...,
   verdict_grades=None)`; the map replaces the letters, looked up ignoring case → verify: adapter
   tests green, every prior adapter test untouched and green.
3. **Row → adapter** (`single_shot.py`, `benchmarks.py`): the field, `_check_verdict_grades`,
   the `verdict_grades=` pin only when set → verify: assembly tests green;
   `test_published_revisions` unchanged and green.
4. **Import both halves**: `python -m screamingface_engine_inspect.importer
   inspect_evals.coconot.coconot:coconot --key coconot_original --task-arg subset=original
   --task-arg grader=screamingface/openrouter/openai/gpt-5.4` (then `contrast`); hand-fill prose,
   tier, licence, judge, map, `has_answer_key=False`, `keep_sample_metadata=True` → verify: row
   tests green; a real prepare yields 1,001 and 379 Cases with empty targets and the rubric in
   private Grading Material.
5. **Guide** (`docs/adding-an-imported-benchmark.md`): replace the stale "rubric IS the target"
   bullet → verify: no doc still says coconot cannot prepare.
6. **Gates**: `uv run .claude/scripts/run_gates.py screamingface-engine` from the repo root (free
   tests only; no paid run).
