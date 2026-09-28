---
id: OME-1115
linear_url: https://linear.app/openmined/issue/OME-1115/evaluate-a-fusion-against-an-imported-inspect-evals-benchmark
status: done
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-04
closed: 2026-09-16
---

# Evaluate a fusion against an imported inspect_evals benchmark

Adapter plugin (spec `docs/spec/2026-09-09-OME-1113-inspect-evals-import.md` §3 + §4):
sealed `screamingface_engine_inspect` package carrying the inspect dependencies behind
the `inspect` uv extra; generic entry-point discovery in engine core (zero plugin
knowledge); `inspect_grade_case` shim wrapping any inspect scorer as a board's
`grade_case` hook with zero per-scorer branches; two proof boards (owner decision
2026-09-15): `inspect-gsm8k` (free-form, check surface, corrective_loop proof) and
`inspect-mmlu` (MCQ, no check surface per the OME-796 elimination-attack rule).

Ledger: `docs/work/2026-09-15-OME-1115-inspect-adapter-plugin.md`
