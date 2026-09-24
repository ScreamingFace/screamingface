---
ticket: OME-1264
stack: screamingface-engine
status: done
started: 2026-09-23
finished: 2026-09-24
---

# OME-1264 — Import the six text LAB-Bench boards (batch 1)

## Intent

First board batch on the ticket: the six TEXT subsets of LAB-Bench (biology
research MCQ; upstream builds every case with the right answer FIRST and
shuffles per run, so the choice-shuffle conservation from PR #1031 is what
makes them importable at all). FigQA and TableQA are image-based
(`ContentImage` inputs) — the text-only bake refuses them by design, OUT of
scope. truthfulqa stays out (task-local record_to_sample + list target).
Stacked on the importer-fix PR #1036.

## Planned changes

- Run the importer ×6 (litqa/LitQA2, suppqa, dbqa, protocolqa, seqqa,
  cloning_scenarios) with policy seeds `--shuffle-seed 7 --choice-shuffle-seed 7`
  (both upstream shuffles are unseeded; 7 matches the tests' pinned example)
- Generated rows land in `pins.py` / `prepare.py` / `boards.py`; agent fills the
  TODO catalogue prose + difficulty tiers from the LAB-Bench paper/dataset card
- `tests/unit/inspect/test_inspect_imported_boards.py`: extend
  `_EXPECTED_FAMILIES`, the seeded-boards set, and add the
  `LAB_BENCH_*_DATASET_REVISION` drift-guard vs upstream's own pinned constant

## Test plan

- Shared board suites cover registration, exam identity, check-surface family,
  reference resolution, prose-not-TODO for the six new keys (parametrized —
  extending the expected sets IS the test change)
- Drift guard: our pins equal `inspect_evals.lab_bench.lab_bench:LAB_BENCH_DATASET_REVISION`
- Offline bake sanity via the existing per-board bake idiom if row shape needs it

## Acceptance

- Six boards registered `inspect-lab_bench_*`, licences cleared (capture warns
  otherwise → back to owner), gates green both lanes, prose filled, no check
  surface on any of them

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/inspect/test_benchmark_declaration.py`
  (six `expected_plugin` rows — the two-axis declaration table also pins every
  imported board).
- **Commits:** the batch commit on `OME-1264-lab-bench-boards` (stacked on
  `OME-1264-importer-mcq-family` / PR #1036).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GREEN;
  inspect lane 266 passed. Capture: revision `5c77cec6…` == upstream's own pin,
  licence cc-by-sa-4.0 (cleared) ×6, counts 199/82/520/108/600/33. Offline bake
  smoke (litqa, hand rows): template renders, choice order shuffled off 'A',
  target letter remaps correctly.
- **Deviations:** (1) append-only skip covers ONLY the three extended
  declaration tables (`_EXPECTED_FAMILIES`, the seeded-boards set,
  `expected_plugin`) — the sanctioned board-batch pattern; flagged in the PR.
  (2) One `ruff --fix` on prepare.py's pins import block: the importer's
  `sorted()` merge orders `GSM8K_DATASET_REVISION` before `GSM8K_DATA_DIR`,
  isort wants the reverse — pre-existing generator quirk, surfaced not fixed.
  (3) FigQA/TableQA excluded (image inputs; text-only bake refuses non-str
  input by design) — 6 boards, not 8.
