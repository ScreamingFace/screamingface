---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done
started: 2026-11-25
finished: 2026-11-25
---

# paid-smoke-prepare-picked-bundles — a paid smoke that names Benchmarks prepares only their datasets

## Intent

The paid smoke (the owner-pressed GitHub Actions button that runs Benchmarks for real, 2 Cases
each) prepares every dataset bundle on every press, whatever is picked. `OME-1522` accepted that
as a limitation because the asset cache makes the extra bundles free. The cache key hashes the
benchmark code, though, so a branch that edits a Benchmark always misses it, and that is the
branch that smokes one Benchmark: run
[45538646440](https://github.com/ScreamingFace/screamingface/actions/runs/45538646440) on the
`OME-1980` branch named `medxpert` and spent 25 minutes (03:15 to 03:40 UTC) preparing all 100
bundles to grade 2 Cases. Fix: a press that names Benchmarks prepares only the bundles those
Benchmarks read.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/prepare.py` — `--list-bundles`
  takes `--for-benchmarks IDS` and prints only the bundles those Benchmarks read, through the
  deployment's registrations; an unknown id exits 1.
- `.github/workflows/screamingface-paid-benchmark-smoke.yml` — the prepare step passes the
  `benchmarks` input (plus `inspect-gsm8k`) to the listing; the cache is not saved after a
  named press.
- `packages/screamingface/justfile` — the local twin `test-paid-benchmarks` does the same.
- `apps/screamingface-engine/tests/unit/test_benchmark_deployment.py` — tests for the flag.

## Test plan

- Named Benchmarks list only their bundles; spaces, empty pieces and repeats are tolerated.
- Two Benchmarks that share one bundle list it once (the bundle comes from the registration,
  not from the Benchmark's name).
- An unknown id exits 1, prints nothing on stdout and names the id on stderr.
- A blank value (`""`, spaces, only commas) lists every bundle, as today.
- `--for-benchmarks` without `--list-bundles` is refused, never silently ignored.

## Acceptance

- A press with `benchmarks: medxpert` asks the preparer for two bundles (`medxpert`,
  `inspect-gsm8k`), not 100.
- A press by scope alone behaves exactly as before, cache save included.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** one commit on `paid-smoke-prepare-picked-bundles`.
- **Gates:** relevant tests only, per owner rule: `tests/unit/test_benchmark_deployment.py` →
  41 passed (it holds every preparer-CLI test); ruff check + format and pyright clean on
  `prepare.py` and the test file. The workflow YAML parses and the justfile parses. The
  workflow's prepare script was run with a stand-in `uv` for four values of the field
  (`medxpert`, ` , `, empty, `a, b`): it asks for `medxpert,inspect-gsm8k` and marks the press
  partial only when an id is named. The real CLI with the `benchmarks` extra prints
  `inspect-gsm8k` and `medxpert` for `"medxpert, inspect-gsm8k"`. Full suites left to CI.
- **Deviations:** (1) A named press also prepares `inspect-gsm8k`: two other paid tests
  (`tests/paid/test_signal_sources_paid.py`) run on every press and read that bundle. (2) A
  named press does not save the asset cache: its asset tree is partial, and saved under the full
  key it would make every later press by scope "hit", download the rest and never save it.
  (3) Not pressed for real: a press spends money and is the owner's. Owner-verify: press with
  `benchmarks: medxpert` on this branch; the prepare step should list two bundles and take about
  a minute.
