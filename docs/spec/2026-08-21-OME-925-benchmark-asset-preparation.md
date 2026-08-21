# OME-925 — Observable benchmark asset preparation

Status: approved (owner, 2026-08-21) · Stack: screamingface-engine

## Problem

OME-875 made the built-in deployment the single source for runtime benchmark discovery and
image asset preparation. The generic preparation seam currently discards the summaries that
prove which answer key was baked, does not normalize expected preparation failures, and is not
yet used by local stack preparation. CI still describes the image as DRACO-only and retains no
BuildKit cache across runs.

## Contract

- A `BenchmarkAssetPreparer` returns a read-only summary-shaped `Mapping[str, Any]`.
- `BenchmarkDeployment.prepare_assets()` invokes each unique bundle once in stable ID order and
  returns the summaries keyed by bundle ID in that same order.
- The built-in CLI emits one JSON object per bundle containing the root, bundle ID, and summary.
- Every family-specific `PrepareError` inherits one shared preparation exception. The generic
  CLI catches only that expected exception, emits one readable error, and remains non-zero.
- Individual family CLIs remain supported; no benchmark bytes, paths, pins, or board sharing
  change.

## Deployment paths

The image and `just stack-prepare` both call:

```text
python -m screamingface_engine.benchmarks.prepare --root <asset-root>
```

Tests derive the image root from `DEFAULT_BENCHMARK_ASSETS_ROOT` and reject every direct
`benchmarks.<family>.prepare` invocation, not only DRACO.

The CI image job uses the supported container-builder/local-registry pattern so its benchmark
build can use the GitHub Actions BuildKit cache while still consuming the base image built in
the same job. The benchmark cache gets its own scope and retains the expensive dataset/corpus
layer across runs.

## Invariants

- The registry-derived one-entrypoint design remains the only complete preparation path.
- DRACO, IFEval, and HealthBench write byte-identical assets to the same directories as before.
- Both HealthBench boards continue sharing one prepared directory.
- Unexpected exceptions still raise with their traceback; only declared preparation refusals
  become concise operator errors.
- Summary values are observations only and never drive runtime behavior.

## Acceptance

- A local root preparation prints counts and family-specific evidence for all three bundles.
- A forced `PrepareError` returns 1 and prints the reason without a traceback.
- Static guards reject family-specific Docker/justfile preparation and verify the derived root.
- The CI benchmark-image step is accurately named and uses a persistent, isolated BuildKit cache.
