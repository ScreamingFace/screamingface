# OME-875 — Registered Benchmark asset deployment

Status: approved (owner, 2026-08-20) · Stack: screamingface-engine

> This specification records the design session that preceded implementation in chat. It was
> committed after the initial draft-PR review exposed the missing repository artifact.

## Problem

`Dockerfile.benchmark` prepares only `/opt/benchmarks/draco`, while the Engine registry advertises
DRACO, IFEval, HealthBench Worst-30%, and HealthBench Professional. IFEval and HealthBench install
their routes against files absent from the deployed image, so preflight rejects those evaluations.

The literal repair—three Docker commands—would restore today's files but retain two independently
maintained declarations: the runtime registry and a Docker preparation list. A future Benchmark
could repeat the same omission.

## Domain model

The Engine currently has four Benchmark identities and three physical asset bundles:

```text
draco                    → draco
ifeval                   → ifeval
healthbench-worst30      → healthbench
healthbench-professional → healthbench
```

- `BenchmarkAssetBundle` is one immutable directory and its build-time preparer.
- `BenchmarkRegistration` pairs exactly one runtime `Benchmark` with exactly one required bundle.
- `BenchmarkDeployment` derives the runtime `BenchmarkRegistry`, deduplicates shared bundles, and
  prepares those bundles beneath the configured root.

Exactly-one cardinality is intentional. There is no assetless or multi-bundle registration until
a real Benchmark requires one; missing preparation is therefore impossible at construction.

## Asset identity and paths

Each Benchmark family owns one stable, lowercase `ASSET_BUNDLE_ID`. Runtime installation and
build-time composition import that same value. Bundle output is always
`assets_root / ASSET_BUNDLE_ID`; no second output-directory field exists.

DRACO and IFEval use their Benchmark ID as the bundle ID. Both HealthBench boards share
`healthbench`, because they select different exams from the same complete 525-row answer key.

## Build interface

Each existing preparer exposes `prepare(out: Path) -> None`; its individual CLI and optional local
probe limit remain available. Deployable images use only:

```bash
python -m screamingface_engine.benchmarks.prepare --root /opt/benchmarks
```

Preparation always invokes every unique required bundle when the Docker layer rebuilds. There is
no directory-exists skip, cleanup policy, build-time truncation, or new smoke identity.

## Invariants

- Adding a built-in requires an asset bundle in the same registration expression.
- Shared bundle identity prepares once; conflicting objects with the same ID fail before download.
- Bundle IDs are safe single directory names.
- Runtime imports do not load build-only dataset dependencies; preparer adapters import lazily.
- DRACO's pinned dataset version, emitted layout, and private rubric routes remain unchanged.
- Missing/corrupt assets still fail at runtime preflight before paid requests.

## Non-goals

- Independent benchmark-image versioning or deployment.
- A public or internal `draco-smoke` identity.
- Runtime asset downloads.
- General zero/many asset cardinality.

## Acceptance

- Registry discovery remains four Benchmark identities.
- Image construction prepares exactly `draco`, `healthbench`, and `ifeval` directories.
- Both HealthBench registrations reference the same bundle object.
- Unit tests fail if Docker returns to a family-specific preparer invocation.
- Exact stack gates and the deployable-image CI job pass.
