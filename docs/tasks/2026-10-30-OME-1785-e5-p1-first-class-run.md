---
id: OME-1785
linear_url: https://linear.app/openmined/issue/OME-1785/make-each-evaluation-a-run-the-engine-owns-lists-and-can-cancel-e5-p1
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1294
created: 2026-10-30
closed:
---

# Make each evaluation a Run the Engine owns, lists and can cancel (E5 P1)

Each `sf.evaluate` becomes a Run record owned by the Engine: an id, an owner, per-Candidate
outcomes, a derived state and 30-day retention. The Client gains `sf.runs` to list, reopen, wait
on and cancel Runs. Runners stay stateless: they publish to `url4-candidate-outcomes`, and the
App is the only database writer.

Delivered as 12 stacked PRs (E1–E8 Engine, C1–C4 Client), each with a sub-issue under this one.

Spec: `docs/spec/2026-10-27-e5-p1-first-class-run.md`.
Plan: `docs/plan/2026-10-30-e5-p1-first-class-run.md`.
Ledger: `docs/work/2026-10-27-e5-p1-first-class-run-spec.md`.
