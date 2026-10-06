---
ticket: OME-1371
stack: screamingface-engine
status: done
started: 2026-10-01
finished: 2026-10-01
---

# coconot-import — import coconot's two halves, judged with no answer key

## Intent

coconot (AI2's "The Art of Saying No") asks whether a model declines what it should and answers
what it should. Its judge grades from a per-category rubric, never an answer key, and it answers in
WORDS (UNACCEPTABLE / ACCEPTABLE / NEITHER; COMPLIANCE / NONCOMPLIANCE / NEITHER) that the scorer
adapter's closed C/I/P/N letter map refuses, so every Case would fail as `invalid_score_value`.
This unit adds a per-Benchmark verdict → grade map, then imports both halves: `coconot_original`
(1,001 should-decline prompts, Inverted Grade, like `xstest_unsafe`) and `coconot_contrast`
(379 look-alike prompts it should answer, like `xstest_safe`). sosbench is out: its licence
forbids redistribution (owner decision 2026-10-01, see OME-1371).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py` — `verdict_grades`
  replaces the letter map when a Benchmark declares one; lookup case-insensitive (the eval's own
  reducer lowercases).
- `.../single_shot.py` — thread `verdict_grades` from the assembly to the grading hook.
- `.../benchmarks.py` — `BenchmarkSpec.verdict_grades`; assembly check (grades in 0..1, words
  distinct ignoring case); revision pin only when set; the two coconot rows.
- `.../prepare.py`, `.../pins.py` — the importer's generated CasesSpec rows + pins.
- `docs/adding-an-imported-benchmark.md` — the "rubric IS the target" bullet is stale.
- Tests under `apps/screamingface-engine/tests/unit/inspect/`.

## Test plan

- Adapter: a declared map turns "UNACCEPTABLE"/"unacceptable" → 1.0; a word outside it → `invalid_score_value`;
  the letter "C" on a mapped Benchmark → `invalid_score_value` (map replaces, never extends);
  inverted + map → 1 − mapped grade; no map → letters unchanged.
- Assembly: grade outside 0..1 refused; two words equal ignoring case refused; the pin appears
  only when set (no published revision moves).
- Rows: each half's map agrees with the eval's own `*_compliance_value_to_float` on every word;
  judge prompt kwargs equal upstream's template/instructions/grade_pattern; original inverted,
  contrast not; metadata kept (the template reads `{refusal}`/`{compliance}`).

## Acceptance

- Both coconot rows assemble and their prepare runs offline-free on the pinned revision (HF read only).
- Exact-match Benchmarks still refuse an empty answer key (pinned by the existing xstest test).
- Free Engine gates green; no published Benchmark Revision moves.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/inspect/test_benchmark_declaration.py` (the
  declared-policy table needs each new Benchmark's row), `docs/tasks/2026-09-25-OME-1371-*.md`,
  and the spec/plan pair `docs/{spec,plan}/2026-10-01-coconot-verdict-grades.md`.
- **Commits:** a two-PR stack, split to stay near the ~500-line cap: `a231bd2ab`
  feat(screamingface-engine): grade judges that answer in words (the `verdict_grades`
  mechanism, spec, plan, guide), then the coconot import on top (rows, pins, row tests, this
  ledger and the mirror).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GREEN — ruff, format,
  pyright 0 errors, layering OK, pytest 5,019 passed / 44 skipped, coverage 93.9%. Inspect lane
  (`--extra inspect`, `tests/unit/inspect`): 598 passed. Real prepare (HF read, no model call):
  1,001 and 379 Cases, empty targets, the rubric text in private Grading Material. No paid run.
- **Deviations:** `--skip-append-only` — owner ruling 2026-10-01: the two registry tables
  (catalogue families, declared policies) gain the coconot rows; no existing assertion changed.
  sosbench not imported (licence, owner decision 2026-10-01). The importer re-sorted one existing
  import line in `prepare.py` (`GSM8K_DATA_DIR`) against ruff's order; reverted by hand.
- **Owner-verify:** the first paid run of both halves — check judge finish reasons, and that
  NEITHER is rare (the judge prompt says "use NEITHER sparingly").
