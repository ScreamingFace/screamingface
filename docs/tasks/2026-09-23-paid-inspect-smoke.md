---
id: OME-1275
linear_url: https://linear.app/openmined/issue/OME-1275/add-a-manually-run-paid-smoke-test-that-runs-every-imported-benchmark
status: in_progress
type: feature
priority: 3
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-23
closed:
---

# Add a manually-run paid smoke test that runs every imported benchmark with real models

Opt-in `paid` pytest lane in `packages/screamingface/tests/paid/`: per imported
inspect_evals board, one real Fusion evaluation (2 flash-tier members + 1 synthesizer)
at 2 cases through the full product path. Shape-only assertions (no infrastructure
failure codes), never score. Gated on `SCREAMINGFACE_TEST_PAID=1` + `OPENROUTER_API_KEY`;
invoked via `just test-paid-inspect` or a `workflow_dispatch`-only workflow. Never a
merge gate. Related: `OME-1243` (golden score locks), `OME-1206` (epic).

Status authority: Linear. Details in the Linear issue and the work ledger
`docs/work/2026-09-23-OME-1275-paid-inspect-smoke.md`.
