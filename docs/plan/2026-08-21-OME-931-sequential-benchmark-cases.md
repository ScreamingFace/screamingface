# OME-931 — Implementation plan

- **Spec:** `docs/spec/2026-08-21-OME-931-sequential-benchmark-cases.md`
- **Linear:** https://linear.app/openmined/issue/OME-931/evaluate-benchmark-cases-sequentially
- **Branch:** `OME-931-sequential-benchmark-cases`
- **Stack:** `screamingface-engine` (`sdlc-python`)

## 1. RED — prove complete Cases do not overlap

In `apps/screamingface-engine/tests/unit/test_benchmark_protocol.py`, add an asynchronous fixture
endpoint that records active Case evaluations across several rows. Run the focused test against
the unmodified protocol and require `max_active == 1`; confirm it fails because the default outer
map admits multiple rows.

Also pin the intended rendered directive on the shared protocol. Keep the existing order and
failure-policy assertions intact.

## 2. GREEN — bind the outer Case map

In `apps/screamingface-engine/src/screamingface_engine/benchmarks/protocol.py`:

- pass `concurrency=1` to the shared outer `iterate(...)`.

Make no URL4 runtime, benchmark-specific builder, or benchmark-revision changes. Revision is the
identity of the thing measured; this unit changes only operational scheduling.

## 3. Reconcile deliberate identities

Run the benchmark protocol and definition tests. Update only the old expectations that are
explicit byte/revision pins for this approved protocol change:

- canonical rendered URL4 SHA-256 values.

Do not change the frozen DRACO or HealthBench revision values, weaken structural assertions, or
change unrelated expectations.

## 4. Verify and deliver

- Run the focused shared protocol and benchmark definition tests.
- Run `uv run .claude/scripts/run_gates.py screamingface-engine` from the repository root.
- Complete the ledger outcome, commit with `Refs: OME-931`, push, and open a PR.
- Add the close-discipline evidence to Linear; leave final Done transition to merge automation.
