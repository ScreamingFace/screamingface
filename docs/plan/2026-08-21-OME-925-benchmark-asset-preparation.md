# OME-925 — Implementation plan: observable benchmark asset preparation

Spec: `docs/spec/2026-08-21-OME-925-benchmark-asset-preparation.md` · Stack:
`screamingface-engine` · Branch: `OME-925-benchmark-asset-preparation`

## 1. Preserve preparation evidence

- Change the preparer port to return `Mapping[str, Any]`.
- Make the three complete-bundle adapters return their existing summaries; give HealthBench an
  explicit professional/worst-30 split.
- Return bundle-keyed summaries from `BenchmarkDeployment.prepare_assets()` and print one JSON
  record per bundle from the orchestrator CLI.

## 2. Normalize expected refusals

- Add a shared benchmark-asset preparation exception.
- Keep each family's `PrepareError` name while deriving it from the shared exception.
- Catch only the shared expected exception at the orchestrator process boundary.

## 3. Enforce one entrypoint everywhere

- Replace the three `stack-prepare` commands with the orchestrator command.
- Strengthen the Dockerfile test to derive the root constant and reject any family preparer.
- Add the equivalent local-preparation invariant and CLI output/error tests.

## 4. Name the CI image build accurately

- Rename the benchmark-image step.
- Preserve the existing, proven base-image handoff and smoke test.
- Defer persistent dataset/corpus caching until its cross-run semantics have a focused design.

## 5. Verify and publish

- Confirm the new focused tests fail before implementation, then make them pass.
- Run `uv run .claude/scripts/run_gates.py screamingface-engine` from the repository root.
- Perform the required wisdom/confidence review, commit with `Refs: OME-925`, push, and open a
  Khoa-style draft PR with Before/After, non-regressions, evidence, and explicit exclusions.
