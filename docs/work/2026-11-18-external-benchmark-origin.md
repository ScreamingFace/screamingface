---
ticket: OME-1960
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-11-18
finished: 2026-11-18
---

# external-benchmark-origin — mark a Benchmark from an outside contributor as external

## Intent

The first Benchmark written outside the team (FutureX-Past, PR 1897) could only call itself
`origin="screamingface"`. Add a third origin, `external`, and a `contributors` field naming
who wrote it, so the catalogue can mark such a Benchmark and credit its author, as
inspect_evals' catalogue does for its External shelf. Spec:
`docs/spec/2026-11-18-external-benchmark-origin.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/provenance.py`
- `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py`
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`
- `packages/screamingface/src/screamingface/_engine/catalog_contract.py`
- `packages/screamingface/src/screamingface/discovery.py`
- Tests: `test_benchmark_provenance.py` (Engine), new
  `inspect/test_external_benchmark_origin.py`, `test_benchmark_provenance_wire.py` (SDK)

## Test plan

- The rule both ways: `contributors` served on an `external` row, refused on the other two
  origins; `inspect_contributors` refused on an `external` row.
- Malformed handles refused; an `external` row naming nobody is a provenance gap.
- An origin outside the closed set is still refused.
- The id: `inspect-` prefix only for `inspect_evals`.
- SDK: the key decodes onto `BenchmarkProvenance`; a malformed list is a catalogue defect.

## Acceptance

- The five numbered criteria in the spec.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the planned ones, plus three the plan did not name at first:
  `apps/scoreboard/src/scoreboard/scores/schemas.py` and its test (the Engine's twin test
  requires every served provenance key to be a declared Scoreboard field), and one word in
  `public-docs/src/pages/sf-client/api/BenchmarksPage.vue`.
- **Commits:** one commit on branch `OME-1960-external-benchmark-origin`, `feat(screamingface-engine): mark a Benchmark from an outside contributor as external`.
- **After review (2026-11-18):** the fidelity checker (`scripts/fidelity_check.py`) kept its own
  two-word origin list, so an `external` Benchmark's record had no valid state; it now knows the
  word and a test pins the list to the Engine's. The "every row has no contributors" test became
  a default-value test, so the PR that flips FutureX-Past edits no test it did not write. The
  onboarding guide names `external`. Wording fixed: the Scoreboard receives the handle only.
- **Owner verify:** merge the PR; then PR 1897 flips FutureX-Past's two rows.
- **Gates:** Engine 9 test files, 1,157 passed; SDK `test_benchmark_provenance_wire.py` and
  `test_public_surface.py`, 27 passed; Scoreboard `test_benchmark_provenance_seed.py`, 24
  passed; ruff, format and pyright clean on the touched files in all three. Full lanes: CI.
- **Deviations:** (1) Scoreboard joined the change (see Actual files). (2) The code was typed
  before the tests, so RED was shown afterwards by removing each new rule in place: 3 tests
  failed (the two-origin refusal and the external id), then the rules were restored.
  (3) Probe, not a committed test: flipping the `musique` row to `external` kept its id
  (`musique`) and revision (`9ef0dcbdf3c310c6`).
