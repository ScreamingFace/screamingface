---
ticket: OME-875
stack: screamingface-engine
status: in_progress
started: 2026-08-20
finished:
---

# OME-875 — Bake every registered Benchmark's assets into the image

## Intent

Make the benchmark image carry the immutable assets for every Benchmark it advertises. The image
currently prepares DRACO only, so deployed IFEval and HealthBench runs fail pre-spend even though
their routes appear in discovery. Linear is the authority:
[OME-875](https://linear.app/openmined/issue/OME-875/bake-every-registered-benchmarks-assets-into-the-benchmark-image-not).

## Planned changes

- Compose runtime Benchmark registration and build-time asset preparation from one declaration.
- Model the present relationship exactly: each registration requires one physical asset bundle;
  multiple registrations may share that bundle.
- Give each Benchmark family one asset-bundle identifier used by both runtime installation and
  image preparation.
- Replace the DRACO-only Docker invocation with one built-in preparation command.
- Keep all existing individual preparer CLIs and runtime missing-asset preflight behavior.

## Test plan

- Assert shared bundles prepare once into stable family-owned directories.
- Assert conflicting bundle identifiers and unsafe directory identifiers fail before preparation.
- Assert all four built-ins declare their physical bundle and Docker calls only the orchestrator.
- Run the exact `screamingface-engine` stack gates and the deployable-image CI build.

## Acceptance

- The built benchmark image contains DRACO, IFEval, and the shared HealthBench assets.
- A future built-in cannot be registered without naming an asset bundle.
- HealthBench Professional and Worst-30% prepare the shared 525-row answer key exactly once.
- DRACO's pinned preparation and missing-asset preflight behavior are unchanged.

## Outcome

- **Actual files:** deployment and preparation modules, built-in composition, the three family
  definitions/preparers, benchmark Dockerfile, deployment tests, and the four OME-875 records.
- **Commits:** `33e13f22` initial draft; review-fix commit is the commit carrying this outcome.
- **Gates:** official `run_gates.py screamingface-engine --skip-append-only` — ALL GATES GREEN;
  the initial draft-PR deployable-image builds also passed.
- **Deviations:** these artifacts were added after the first implementation commit when the draft
  PR review identified that the mandatory agent record had been omitted. They record the approved
  design honestly rather than claiming to predate the code. The append-only guard was skipped with
  owner approval because the review fix intentionally replaces the initial commit's zero/many
  synthetic test with the approved exactly-one contract; no inherited pre-ticket test changed.
