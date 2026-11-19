# Plan — mark a Benchmark from an outside contributor as external

Spec: `docs/spec/2026-11-18-external-benchmark-origin.md`. One unit, three landings
(`apps/screamingface-engine`, `packages/screamingface`, `apps/scoreboard`), one ticket (owner
decision 2026-11-18: one wire key, so one PR), `sdlc-python` loop.

1. **Engine, the origin.** `benchmarks/definition.py`: add `external` to `BenchmarkOrigin` and
   `_BENCHMARK_ORIGINS`; add `contributors: tuple[str, ...] | None = None` to `Benchmark`.
2. **Engine, the rule.** `benchmarks/provenance.py`: add the key to `ProvenanceFields`; in
   `_check_people` validate the handles and refuse the field unless origin is `external`;
   serve it in `provenance_metadata`; name it in `provenance_gaps` when an `external` row
   leaves it out.
3. **Engine, the id.** `single_shot.py` `imported_benchmark_id`: the `inspect-` prefix only
   for `inspect_evals`, so `external` takes the bare key.
4. **Engine, the row type.** `screamingface_engine_inspect/benchmarks.py`: the field on
   `BenchmarkSpec`, which the assembler passes through by `PROVENANCE_FIELD_NAMES`.
5. **SDK.** `_engine/catalog_contract.py`: add the key to `_PROVENANCE_HANDLE_KEYS` (the
   Engine's twin test asserts the lists match). `discovery.py`: the field on
   `BenchmarkProvenance`, last, so no positional argument shifts.
6. **Scoreboard.** `scores/schemas.py`: declare the field on `ProvenanceSchema` (the Engine's
   twin test asserts every served key is seeded).
7. **Docs.** One word in the SDK's API page field list.
8. **Tests.** Engine: the rule both ways, malformed handles, the gap, the closed set, the id
   for all three origins. SDK: decode, malformed list, constructor. Scoreboard: stored and
   served. Existing tests stay unedited.
9. **Gates.** The touched and dependent test files per landing, ruff, format and pyright on
   the touched files. CI runs the full lanes.
10. **After merge.** PR 1897 merges `main` and flips its two rows.
