---
ticket: OME-1513
stack: screamingface
status: done
started: 2026-10-08
finished: 2026-10-08
---

# OME-1513-pr2-musique-notebook — the MuSiQue example notebook

## Intent

PR #1292 served MuSiQue-Ans as `musique` but shipped no example notebook: every hand-built
Benchmark has one (`06_draco` … `13_contracteval`), the imported boards share
`12_inspect_evals_benchmarks`, and the musique row pointed at that shared notebook although it
is ours and has a story the imported boards do not (three Named Scores, cited paragraphs, a
reply reader that takes the last label). A researcher opening the catalogue card lands on a
notebook that never mentions the Benchmark. This unit adds `15_musique.ipynb` in the
hand-built pattern, points the row at it, and writes the rule into the local-Task onboarding
section so the next local Task ships one too.

## Planned changes

- `packages/screamingface/scripts/build_notebooks.py`: `_musique_e2e()` + registry entry.
- `packages/screamingface/examples/15_musique.ipynb`: generated, output-free.
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`: musique row
  `notebook="15_musique"`.
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md`: a local Task ships a
  notebook like a hand-built Benchmark.
- This ledger; the OME-1513 mirror stays `in_progress` (per-Benchmark investigation open).

## Test plan

- `scripts/check_notebooks.py` (deterministic regeneration) and
  `tests/test_example_notebooks.py` (every `case.<attr>` the notebook reads exists on
  `CaseResult`) cover the new notebook by enumeration.
- Engine: `test_published_revisions.py` must not move (the notebook pointer is Provenance,
  not a revision input); `test_benchmark_provenance.py` shape tests.
- No paid run: the notebook ships output-free (owner instruction, 2026-10-08).

## Acceptance

- `15_musique.ipynb` exists, regenerates byte-identically, reads only real `CaseResult`
  attributes, and the catalogue card for `musique` names it.
- The musique revision literal is unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (builder + generated `15_musique.ipynb`, the row's `notebook=`,
  the onboarding bullet, this ledger). The other notebooks regenerate with only a package
  version stamp changed and were left untouched.
- **Commits:** see the PR; one squash.
- **Gates:** Engine gate on push (append-only, ruff, format, pyright, layering, pytest with
  coverage); SDK by hand: `check_notebooks.py` deterministic, `test_example_notebooks.py` +
  passthrough 17 passed, full SDK suite with the notebook extra; Engine targeted 447 passed,
  musique revision literal unchanged (the notebook pointer is Provenance, not identity).
- **Deviations:** no infographic card under `examples/assets/` (the 13_contracteval precedent
  ships without one; owner asked for the notebook only). Not executed against a stack: ships
  output-free like every example; the first paid run of it is the owner's.
- **Owner-verify:** open `15_musique.ipynb` against `just local-stack-notebooks` once and
  read the three Named Scores and the per-case `hop_type` line come out as written.
