---
id: OME-829
linear_url: https://linear.app/openmined/issue/OME-829/ship-the-draco-check-adapter-draco-passv1-so-correctiveloop-runs-on
status: In Progress
priority: P1
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-14
parent: OME-796
---

# Ship the DRACO check adapter (draco-pass.v1) so CorrectiveLoop runs on DRACO

Stage 3 of the OME-796 plan as its own PR, rebased onto `main` after PR #598 merged:
input-addressed check-surface route on the DRACO benchmarks (one judge pass
over the case rubric), pass criterion `draco-pass.v1` (normalized weighted score ≥ 0.7,
criterion id carried in the route), axis-level-only feedback with a leak test,
`expected_check_cost: "paid"` + client spend surfacing, judge-call hygiene
(exact-request cache identity and distinct bounded retry keys), and the `sf.CorrectiveLoop` cell in
the DRACO notebook. Concrete adapter — the `rubric_check` template extraction is
OME-830's job.

Spec: `docs/spec/2026-08-14-OME-796-corrective-loop-generalization.md`
Plan: `docs/plan/2026-08-14-OME-796-corrective-loop-generalization.md`
Ledger: `docs/work/2026-08-14-OME-829-draco-check-adapter.md`
