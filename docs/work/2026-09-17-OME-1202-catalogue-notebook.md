---
ticket: OME-1202
stack: py-screamingface
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1202 — Example notebook shows the imported benchmark catalogue and runs one

## Intent

The imported inspect_evals boards (OME-1116) and the two-group listing (OME-1114) exist but have no front door: no `examples/` notebook shows a researcher what's on the shelf or how to run an imported board. This unit adds the guided-pass notebook: open the catalogue, see ours vs imported as two groups, pick an imported board, run a fusion at small limit, show the report widget.

## Planned changes

- `packages/screamingface/scripts/build_notebooks.py` — new `_imported_catalogue()` builder + registry entry (notebooks are generated artifacts, never hand-authored)
- `packages/screamingface/examples/12_imported_benchmarks.ipynb` — generated output
- `packages/screamingface/tests/test_imported_catalogue_notebook.py` — contract test (listing → imported board → fusion evaluate; public surface only; never pays by default)
- Ledger + `docs/tasks/` mirror

## Test plan

- Notebook passes the SDK's deterministic notebook check (output-free, deterministic) — the gate that already guards `examples/*.ipynb`
- Listing cell uses the real `sf.benchmarks.list()` idiom copied from existing notebooks; shows both origin groups
- Evaluate cell uses `sf.evaluate(fusion, benchmark="inspect/…", limit=…)` public-surface idiom only — no engine internals, no inspect runner
- Free-tier cells agent-runnable; paid run cells owner-only (paid-runs rule)

## Acceptance

- Notebook merged under `examples/`; listing cell shows both groups; an imported board evaluates end to end at small `limit` (paid pass executed by owner)

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `scripts/build_notebooks.py` (`_imported_catalogue()` + registry), generated `examples/12_imported_benchmarks.ipynb`, `tests/test_imported_catalogue_notebook.py`, ledger + mirror.
- **Commits:** feature commit + docs-close commit on this branch (`Refs: OME-1202`).
- **Gates:** `run_gates.py screamingface` ALL GREEN — ruff check/format, pyright, pytest (cov ≥95%), check_notebooks, uv build, check_distribution. New contract tests written RED-first, then green.
- **Deviations:** run cells follow the existing benchmark-notebook idiom (direct `sf.evaluate` at small `limit` + prose warning), not a `RUN_EVALUATION` guard — matches 07/08/11. Finding surfaced, not fixed here: no current environment serves the imported boards — the local runtime can't install the `inspect` extra (declared uv conflict with `litellm`) and the engine Dockerfile runs `uv sync` without `--extra inspect`; the notebook says so and points `SCREAMINGFACE_ENGINE_URL` at an inspect-capable engine. End-to-end acceptance (listing shows two groups; imported board evaluates) is the owner's paid pass against such an engine. README's `## Examples` list is stale (pre-existing) — left untouched.
- **Owner-verify:** run the notebook against an inspect-capable engine: listing shows both groups; `inspect-gsm8k` fusion at `limit=2` completes.
