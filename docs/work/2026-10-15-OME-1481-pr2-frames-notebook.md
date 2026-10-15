---
ticket: OME-1481
stack: screamingface
status: done
started: 2026-10-15
finished: 2026-10-15
---

# OME-1481-pr2-frames-notebook — the FRAMES example notebook

## Intent

PR #1422 serves FRAMES (articles given) as `frames_oracle` and pointed its row at the shared
`12_inspect_evals_benchmarks` notebook, which never mentions it. A local Task ships its own
notebook like a hand-built Benchmark (the MuSiQue rule, OME-1513): this unit adds
`17_frames.ipynb` and points the row at it, so a researcher opening the catalogue card lands on
a notebook that explains the long prompts, the 200k window, the Judge and the cost.

## Planned changes

- `packages/screamingface/scripts/build_notebooks.py`: `_frames_oracle_e2e()` + registry entry.
- `packages/screamingface/examples/17_frames.ipynb`: generated, output-free.
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`: the
  `frames_oracle` row's `notebook="17_frames"`.
- This ledger; the OME-1481 mirror closes (owner steps below).

## Test plan

- `scripts/check_notebooks.py` (deterministic regeneration) and
  `tests/test_example_notebooks.py` (every `case.<attr>` the notebook reads exists on
  `CaseResult`) cover the new notebook by enumeration.
- Engine: `test_published_revisions.py` must not move (the notebook pointer is Provenance, not
  a revision input); the provenance shape tests.
- No paid run: the notebook ships output-free.

## Acceptance

- `17_frames.ipynb` exists, regenerates byte-identically, reads only real `CaseResult`
  attributes, and the `frames_oracle` card names it; the revision literal is unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Regenerating also rewrote five other notebooks' version stamp
  (`0.1.1.post8` → `0.1.2`) and nothing else; those were restored, as the MuSiQue PR did.
- **Commits:** see the PR.
- **Gates:** SDK: `check_notebooks.py` exit 0, `test_example_notebooks.py` +
  `test_benchmark_provenance_wire.py` 30 passed, ruff and format clean, pyright clean on
  `build_notebooks.py`. Engine: `test_published_revisions.py`, `test_local_task_frames.py`,
  `test_benchmark_provenance.py`, `test_benchmark_provenance_conformance.py` 278 passed with
  the inspect extra; `frames_oracle` stays at `eb27d52bf8431b07`. Full suites: pre-push hook
  and CI.
- **Numbers in the notebook:** from the prepared bundle: 822 Cases, 76,504,153 prompt
  characters (mean 93,071, longest 728,489), about 19M input tokens per panel member at ~4
  characters a token; the synthesiser reads the articles too, so a two-member panel is about
  57M.
- **Deviations:** no e2e golden. The e2e lane's golden needs one paid recorded run first
  (`tests/e2e/README.md` step ③, the owner's); the board is not added to the lane's `BOARDS`
  until a recording exists. Not executed against a stack: ships output-free like every example.
- **Owner-verify:** (1) open `17_frames.ipynb` against `just local-stack-notebooks` and run it
  with `limit=5`, checking that the Judge's explanation and the reasoning types print per scored
  case and the failure codes per failed case;
  (2) one paid full run of a solo Candidate on `frames_oracle` (ticket acceptance 7) to put
  beside the paper's 0.729, confirm the tier (`medium`), and record it for the e2e golden
  (`just e2e-bless …`, a follow-up PR).
