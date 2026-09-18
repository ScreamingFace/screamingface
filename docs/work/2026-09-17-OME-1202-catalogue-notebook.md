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
- `apps/screamingface-engine/Dockerfile.benchmark` — comment recording that its preparer depends on the base image's inspect extra; then (owner-directed, same branch) replaced its hand-written `uv pip install "datasets==5.0.0" "pdfplumber" "python-docx"` with `uv sync --frozen --no-dev --extra benchmarks`
- `apps/screamingface-engine/pyproject.toml` + `uv.lock` — the preparer's packages become declared extras instead of a post-sync `uv pip install`. Two extras, nested: `inspect` (what a DEPLOYED Engine needs — now also pinning `datasets==5.0.0`, which `inspect-evals` requires but does NOT pin, so resolving it alone floated the extractor that bakes GDPval's answer key) and `benchmarks = ["screamingface-engine[inspect]", pdfplumber, python-docx]` (what BUILDING assets needs). Kept separate because the base image ships and the prepare stage is thrown away: folding the readers into `inspect` would put 8 extra packages (~25MB: pdfplumber, pdfminer-six, pypdfium2, python-docx, lxml, cryptography, cffi, pycparser) in every deployed Engine. Owner chose the nested shape over one flat extra. Side effect of the `datasets` pin: `s3fs` 2026.6.0 → 2026.4.0 in the lock, matching what the old pip-install line already produced at build time.
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

- **Actual files:** `scripts/build_notebooks.py` (`_inspect_evals_boards()` + registry), generated `examples/12_inspect_evals_benchmarks.ipynb` (renamed from `12_imported_benchmarks` by the owner late in the work), `README.md` example entry, `packages/screamingface/justfile` + a new repo-root `justfile`, and — as the ticket grew — `apps/screamingface-engine/` (`single_shot.py`, `Dockerfile`, `Dockerfile.benchmark`, `benchmarks/prepare.py`, `benchmarks/deployment.py`, two test modules). A contract test (`tests/test_imported_catalogue_notebook.py`) was written red-first and then **deleted at owner instruction** during review — review found its paid-run assertion vacuous (this notebook family uses the direct-`sf.evaluate` idiom, never the `RUN_EVALUATION` guard it asserted against), and the owner judged the remaining assertions not worth a test file.
- **Commits:** thirteen on this branch, all `Refs: OME-1202`, in PR #978.
- **Gates:** `run_gates.py screamingface` and `run_gates.py screamingface-engine` ALL GREEN. Two runs needed `--skip-append-only`, both owner-approved: the contract-test deletion above, and splitting `test_every_builtin_board_publishes_screamingface_origin` (below). CI's "Build the deployable images" job passed, which is what verifies the Dockerfile change.
- **Deviations — scope grew well past the notebook.** Run cells follow the existing benchmark-notebook idiom (direct `sf.evaluate` at small `limit` + prose warning), not a `RUN_EVALUATION` guard — matches 07/08/11, so Run All does spend. Building the notebook meant running it, and running it surfaced three defects the owner directed into this PR rather than separate tickets:
  1. **Every imported board published `origin="screamingface"`.** `Benchmark.origin` defaults to that and the import lane never overrode it, so the two-group listing (OME-1114's whole feature) rendered one group. Fixed at the single board factory in `single_shot.py`. The existing origin test passed throughout because it built its own benchmark with the origin passed by hand; the new pin asserts over the real `board_registrations()`. A second test was passing *because* of the defect — it iterates the whole deployment, which folds in plugin boards — so it split into a presence check over every deployed board and an authorship check over `BUILTIN_REGISTRATIONS`.
  2. **No deployed Engine could serve the imported boards**: the image synced without `--extra inspect`, so `inspect_available()` returned nothing and the boards never registered. Fixed in `Dockerfile`. Nearly mis-diagnosed: the `inspect`×`runtime` conflict is about **`packages/screamingface`'s** `litellm` pin, and the Engine depends on neither, so one Engine environment holds every preparer's dependencies.
  3. **Asset preparation was all-or-nothing.** Preparers that refuse a non-empty directory re-raised on every sibling that had finished, so one interrupted run could only be recovered by deleting and re-downloading everything. Added `--bundle`/`--list-bundles` over an `only=` selector; the recipe resumes using `cases.json` (written last) as the completion marker.
- **Verified live, not inferred:** `/v1/benchmarks` went from 17 boards all claiming `screamingface` to `{screamingface: 7, inspect_evals: 10}`. Owner's paid run of `inspect-gsm8k` with the three-model fusion at `limit=2`: score 1.0, coverage 1.0, 2/2 correct, $0.00443 metered, 3,051 of 3,794 output tokens spent on reasoning.
- **Owner-verify:** DONE — both origin groups render and the `inspect-gsm8k` fusion completes. Not covered here: OME-1116's remaining paid `limit=50` acceptance runs and a `corrective_loop` on a free-text board.
- **Surfaced, not fixed:** the report widget renders benchmark text containing `$` as LaTeX (GSM8K's prompt garbles on screen) — filed as `OME-1226`, independent of this PR. The owner also removed the notebook's inspect-export sections late in the work; the finding they carried (there is no service accepting `.eval` uploads, and inspect_evals publishes no results leaderboard) survives only in OME-1111's architecture diagram.
