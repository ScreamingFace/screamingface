---
id: OME-1246
linear_url: https://linear.app/openmined/issue/OME-1246/contracteval-runs-crash-when-a-case-fails-instead-of-reporting-the
status: done
type: bug
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-21
closed: 2026-09-21
---

# ContractEval runs crash when a case fails instead of reporting the failed case

ContractEval's `polarity_mismatch` and `contracteval_grading_failed` never joined
the engine's declared failure vocabulary (PR #984 crossed the OME-1233 close in
flight), so the `Failure` validator crashes a run that should publish a failed
case; one engine test is red on `main`. Fix: declare both codes (append-only)
on BOTH sides — the OME-1235 conformance test pins the engine and SDK lists
equal, so they can only move in one PR (#1002). Details: the Linear issue +
`docs/work/2026-09-21-OME-1246-declare-contracteval-failure-codes.md`.
