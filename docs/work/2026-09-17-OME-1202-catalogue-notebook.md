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
- `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py` — stamp `origin="inspect_evals"` on imported boards (defect found while verifying the notebook; owner directed the fix into this PR rather than a new ticket)
- `apps/screamingface-engine/tests/unit/test_inspect_imported_boards.py` — pin the origin over the real registrations
- `apps/screamingface-engine/tests/unit/test_benchmark_origin.py` — split the over-reaching assertion (owner-approved prior-test change)
- `packages/screamingface/justfile` — `just local-stack-notebooks` (one command: bake → stack → inspect-capable Engine → Jupyter) + owner-requested hardening of the bless recipes (`[confirm]` on the golden rewrite, `require()`/`path_exists()` preconditions, hoisted `blesser`, `set default-list`)
- `apps/screamingface-engine/Dockerfile` — `--extra inspect` on both sync layers, so a deployed Engine registers the imported boards at all (and the benchmark image, built FROM it, can bake their snapshots)
- `apps/screamingface-engine/Dockerfile.benchmark` — comment recording that its preparer depends on the base image's inspect extra
- `packages/screamingface/scripts/build_notebooks.py` (all 9 setup cells) + `README.md` — point at the recipe
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/{prepare,deployment}.py` — `--bundle`/`--list-bundles` and a `only=` selector, so an interrupted bake resumes instead of forcing every sibling bundle to be deleted and re-downloaded
- `justfile` (repo root) — a `mod` entry so component recipes are reachable from the root; `just` searches upward only, so running it anywhere above `packages/screamingface` found nothing. A module runs its recipes in the module's directory, so nothing in the component justfile changed.
- Ledger + `docs/tasks/` mirror

## Test plan

- Notebook passes the SDK's deterministic notebook check (output-free, deterministic) — the gate that already guards `examples/*.ipynb`
- Listing cell uses the real `sf.benchmarks.list()` idiom copied from existing notebooks; shows both origin groups
- Evaluate cell uses `sf.evaluate(fusion, benchmark="inspect/…", limit=…)` public-surface idiom only — no engine internals, no inspect runner
- Free-tier cells agent-runnable; paid run cells owner-only (paid-runs rule)

## Acceptance

- Notebook merged under `examples/`; listing cell shows both groups; an imported board evaluates end to end at small `limit` (paid pass executed by owner)

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `scripts/build_notebooks.py` (`_imported_catalogue()` + registry), generated `examples/12_imported_benchmarks.ipynb`, ledger + mirror. A contract test (`tests/test_imported_catalogue_notebook.py`) was written red-first and then **deleted at owner instruction** during review — review found its paid-run assertion vacuous (this notebook family uses the direct-`sf.evaluate` idiom, never the `RUN_EVALUATION` guard it asserted against), and the owner judged the remaining assertions not worth a test file. Gates re-run with `--skip-append-only` for that deletion, owner-approved.
- **Commits:** feature commit + docs-close commit on this branch (`Refs: OME-1202`).
- **Gates:** `run_gates.py screamingface` ALL GREEN — ruff check/format, pyright, pytest (cov ≥95%), check_notebooks, uv build, check_distribution. Re-run with `--skip-append-only` after the owner-instructed test deletion.
- **Deviations:** run cells follow the existing benchmark-notebook idiom (direct `sf.evaluate` at small `limit` + prose warning), not a `RUN_EVALUATION` guard — matches 07/08/11, so Run All does spend. No environment ships the imported boards yet: the SDK's `runtime` extra can never co-install `inspect-ai` (declared uv conflict with `litellm`) and the engine Dockerfile syncs without `--extra inspect`. Review round 1 (PR #978) found the notebook promised the local path worked anyway while calling `sf.benchmarks.get("inspect-gsm8k")` unconditionally; fixed by an explicit origin check that stops with directions, plus a concrete "run an inspect-capable Engine from a checkout" recipe in section 0 (`uv sync --extra inspect` → `benchmarks.prepare` → `local:create_local_app` on a free port; the built-in deployment already folds in the plugin's `discovered_registrations()`). Also flagged and fixed: "swap the id" guidance now says to adapt the synthesis prompt for MCQ boards. End-to-end acceptance (two groups render; `inspect-gsm8k` evaluates) is the owner's paid pass. README's `## Examples` list is stale (pre-existing) — left untouched.
- **Owner-verify:** run the notebook against an inspect-capable engine: listing shows both groups; `inspect-gsm8k` fusion at `limit=2` completes.
