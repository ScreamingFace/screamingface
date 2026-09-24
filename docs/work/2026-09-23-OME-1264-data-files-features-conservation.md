---
ticket: OME-1264
stack: screamingface-engine
status: done
started: 2026-09-23
finished: 2026-09-24
---

# OME-1264 — Conserve `data_files` + `features` in the inspect importer (extension 2 of 2)

## Intent

Conserve the two co-occurring `hf_dataset` kwargs the `infinite_bench_*` family
(9 boards) needs: `data_files` (forwarded to `datasets.load_dataset`, upstream
shape `{"<task>": "<task>.jsonl"}`) and `features` (a `datasets.Features`
schema). Key design deviation from the ticket sketch: upstream's `features` is a
MODULE-LEVEL constant (`inspect_evals.infinite_bench.constants:ft`), so the row
POINTS at it with a dotted reference resolved at bake (the existing
`record_to_sample`/`system_message` pattern) instead of serializing
`Features.to_dict()` into generated literals — less code, no new injection
surface, matches "rows POINT at the eval's own code". Stacked on the
`shuffle_choices` branch (PR #1031); boards ride later batch PRs.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`
  - `data_files` + `features` join `_REPRODUCED_DATASET_KWARGS`
  - `TaskFacts.data_files` (str | dict[str, str] literal; other shapes refused by
    name) and `TaskFacts.features` (dotted ref via `_template_attribute` identity
    search; unresolvable → refusal, never a silent drop)
  - `render_fragments`: `{PREFIX}_DATA_FILES = <json literal>` pin (json.dumps —
    double quotes survive the ruff-format gate) + inline `features="mod:attr"`
    snapshot line
  - `_refuse_injectable_text`: charset-walk data_files strings + the features ref
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`
  - `SnapshotSpec.data_files` / `SnapshotSpec.features`
  - `_load_rows` forwards `data_files` and the resolved `features` (must be a
    `datasets.Features` instance, else PrepareError)
- `apps/screamingface-engine/src/screamingface_engine_inspect/boards.py`
  - `_revision_pins` appends both when set (they select WHICH data loads —
    exam identity)
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md` — conserved
  note + refusal rows
- Tests appended in `tests/unit/inspect/` (importer, snapshots, imported-boards)

## Test plan

- introspect records `data_files` dict + `features` as a dotted pointer fact
- introspect refuses: `features` with no module attribute; an exotic
  `data_files` shape (INVARIANT: conserved — reproduced or refused, never dropped)
- `main()` end-to-end: pin + snapshot lines land; round-trip constructs the real
  `SnapshotSpec`
- injection: hostile `data_files` string refused at generate
- `_load_rows` forwards both to `datasets.load_dataset` (monkeypatched loader,
  real `datasets.Features` — offline); refuses a features ref resolving to a
  non-Features
- `_revision_pins` carries both when set, neither otherwise

## Acceptance

- `data_files` + `features` conserved end-to-end; `infinite_bench_*` introspects
  past the dataset-kwargs guard (board batches remain later work)
- All prior tests untouched and green; gates green in both lanes

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; helpers `_conserved_data_files` /
  `_features_reference` / `_dataset_selection_fragments` in importer.py.
- **Commits:** the feature commit on `OME-1264-data-files-features` (stacked on
  `OME-1264-shuffle-choices` / PR #1031).
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN **including
  append-only — no skip**; inspect lane 232 passed. Smoke:
  `infinite_bench_passkey` + `infinite_bench_longbook_choice_eng` introspect
  cleanly offline (data_files + features conserved; remaining flags are the
  system-message solver + truncate_input_solver, batch-time review items).
- **Deviations:** (1) `data_files` conserves the dict[str, str] shape ONLY —
  a bare-str data_files still refuses by name, which keeps the prior shim
  flatten test (`data_files="rows.parquet"`) green untouched and is all
  infinite_bench needs (YAGNI). (2) `features` is a dotted POINTER at the
  eval's module constant, not the ticket sketch's `Features.to_dict()`
  serialized literal — less code, no new injection surface, matches the
  rows-point-never-copy convention.
