# Plan — record where each hand-built bundle's Cases came from (OME-1492 PR 3)

Spec: `docs/spec/2026-10-07-OME-1492-pr3-hand-built-provenance.md` · ledger:
`docs/work/2026-10-07-hand-built-provenance.md` · stacked on PR 1 (#1268) · landing: the Engine's
core Benchmarks, plus the paid smoke's press-page helper in the SDK tests. Nothing paid runs.

Recorded 2026-10-07 at review time: the steps below are the ones the PR 3 session followed, kept
here so the approvals file and the ledger have a plan to point at.

## Owner calls (2026-10-07)

- The hand-built blocks ship as their own PR 3, after PR 1 (owner call 2026-10-06, "b").
- Shared bundles: a small Benchmark-to-bundle map in the SDK helper, not an Engine change.
- gdpval reports `excluded` as loaded minus kept (220 / 118 / 102), so the row adds up.
- ifeval lists its vendored official file as a second source, because that text wins on key 2785.
- The SDK helper's prior-test edit (the map, and a dash for a block with no inspect-evals pin) is
  approved and pinned in `.claude/test-change-approvals/OME-1492.json`.

## Steps

Each line: step → verify.

1. **Move the label writer to core** — `screamingface_engine/benchmarks/bundle_provenance.py`
   (`write_provenance`, `read_provenance`, `hugging_face_source`, `hand_built_provenance`, the
   Case Source words); the plugin's `replay_provenance.py` imports it. → verify:
   `check_layering.py` green (core never imports the plugin).
2. **RED/GREEN per preparer** (draco, ifeval, healthbench, gdpval, medxpert, contracteval): append
   one test each, using the shared checks in `tests/unit/_bundle_provenance_checks.py`, that the
   block is written once, before `cases.json`, with the declared revision, the counts, and no Case
   text; then write the block where each preparer writes `cases.json`. → verify: green, no prior
   test edited.
3. **The press page** — the SDK helper maps draco-3pass, gdpval-text and the healthbench variants
   to their shared bundles, and shows a dash when there is no inspect-evals pin. → verify: free
   paid-lane tests green with `SCREAMINGFACE_TEST_PAID=1`.
4. **Gates** — `run_gates.py screamingface-engine` and `run_gates.py screamingface`, both with
   `--base` at PR 1's tip; the approvals file pins the SDK helper edit. → verify: both green, no
   skip flag.
5. **Docs in the PR** — spec, this plan, ledger outcome, one dated line in the OME-1492 mirror.
