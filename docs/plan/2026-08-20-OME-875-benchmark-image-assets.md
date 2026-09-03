# OME-875 — Implementation plan: registered Benchmark assets

Spec: `docs/spec/2026-08-20-OME-875-benchmark-image-assets.md` · Stack:
`screamingface-engine` · Branch: `OME-875-benchmark-assets`

> Recorded after the initial implementation commit, following draft-PR review. The refinement
> steps below reflect the owner-approved design and do not claim retrospective RED-first order.

## 1. Deployment seam

Add `benchmarks/deployment.py` with three concepts:

- `BenchmarkAssetBundle(id, prepare)` validates a path-safe physical bundle identity.
- `BenchmarkRegistration(benchmark, asset_bundle)` requires exactly one bundle.
- `BenchmarkDeployment(registrations)` derives the runtime registry, rejects conflicting bundle
  IDs, deduplicates shared objects, and prepares each unique bundle in stable order.

Keep `BUILTIN_BENCHMARKS` as the runtime-compatible registry derived from
`BUILTIN_DEPLOYMENT`, so existing callers do not change.

## 2. Family-owned asset identity

Define `ASSET_BUNDLE_ID` beside each family's runtime installation decision:

- DRACO: `ASSET_BUNDLE_ID = BENCHMARK_ID`
- IFEval: `ASSET_BUNDLE_ID = BENCHMARK_ID`
- HealthBench: `ASSET_BUNDLE_ID = "healthbench"` in the shared exam module

Use it in the runtime install path, the built-in bundle composition, and individual CLI defaults.

## 3. Preparation interface and image

- Add complete-bundle `prepare(out: Path) -> None` functions without removing probe-capable CLIs.
- Add `benchmarks.prepare`, which calls `BUILTIN_DEPLOYMENT.prepare_assets(root)`.
- Replace the DRACO-only Docker command with the single deployment preparation command.

## 4. Verification

- Unit-test bundle validation, exactly-one registration, shared preparation, built-in mappings,
  and the Docker orchestration invariant.
- Run `uv run .claude/scripts/run_gates.py screamingface-engine` from the repository root.
- Push the draft PR and require its deployable-image build to pass.
- Repeat independent Standards and OME-875 Spec reviews; keep the PR draft until both are clean.

## 5. Review-driven corrections

- Remove speculative assetless/multi-bundle support; present cardinality is exactly one.
- Eliminate duplicated output-directory strings through family-owned bundle IDs.
- Move the worktree into `.claude/worktrees/OME-875-benchmark-assets`.
- Add the task, spec, plan, and work records omitted before the initial commit.
