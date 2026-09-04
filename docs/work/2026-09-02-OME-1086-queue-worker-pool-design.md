---
ticket: OME-1086
stack: repo
status: in_progress
started: 2026-09-02
finished:
---

# OME-1086 — Design the queue-backed worker-pool runner (spec + plan only)

## Intent

`OME-1058` asks infrastructure to size a node against a Pod count the client
chooses. That is a symptom. The cause is Job-per-run: the number of Pods is a
variable the SDK sets (`_MAX_CANDIDATES_IN_FLIGHT = 8`), while the quota and the
node are constants the operator set — and `OME-1064` recorded what happens when
they disagree (23 minutes of silent non-execution).

`OME-1064` names the long-term direction and puts it explicitly out of its own
scope: stop creating one Pod per run; use a fixed pool of workers pulling from a
queue, so Pod count is constant and the queue is the elastic part. This unit
produces the spec and the implementation plan for that direction. It writes **no
production code** — the seven sub-issues of `OME-1086` do that.

## Planned changes

- `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md` — the design.
- `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md` — the per-unit
  implementation plan, one section per sub-issue, written so another agent can
  execute a unit without re-deriving the design.
- `docs/tasks/2026-09-02-OME-108{6,7,8,9}-*.md`, `…-OME-109{0,1,2,3}-*.md` — the
  eight work-item mirrors (epic + seven sub-issues).

No file under `apps/` or `packages/` is touched by this unit.

## Test plan

Not applicable — this unit produces documents. The verification is the spec
self-review checklist (placeholders, internal consistency, scope, ambiguity)
plus owner review of the written artifacts.

The test *strategy* for the implementation lives in the spec's "Test strategy"
section and is decomposed per unit in the plan; each sub-issue runs the normal
`sdlc-python` RED-first loop against it.

## Acceptance

- Spec and plan exist, are internally consistent, and carry no placeholders.
- Every design decision the owner took on 2026-09-02 is recorded with its
  rationale, including the two accepted regressions and the fairness split.
- The three traps found during blast-radius mapping are pinned in the spec with
  a named test obligation each.
- Eight Linear issues exist with the correct labels, a real dependency graph,
  and a mirror each.
- Owner has reviewed and approved the spec before any sub-issue starts.

## Decisions taken (owner, 2026-09-02)

| Decision | Choice | Rejected |
| -- | -- | -- |
| Isolation | Subprocess per run inside the worker | Asyncio task per run; single-slot pool |
| Migration | Replace `K8sJobRunner` outright | Coexist behind the factory flag; local-first |
| NATS durability | In scope as a hard prerequisite (`OME-1093`) | Leave to a later unit |
| Deployed fairness | In scope, as run-level + spawn-time budget (`OME-1091`) | Leave to `OME-908` alone |
| Retire the Job adapter | In scope, same plan (`OME-1092`) | Later unit |
| Queue-depth autoscaling | Out of scope | KEDA in this epic |

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
