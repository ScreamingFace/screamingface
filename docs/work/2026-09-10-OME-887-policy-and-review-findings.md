---
ticket: OME-887
stack: repo
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-887 — Deployment policy and review findings

## Intent

Add the approved full/off deployment-policy split, defer aggregate mode, and address review findings about decoder memory, structured bridge-loss reporting and stale operation presentation. Documentation only; product implementation remains separately gated.

## Planned changes

- Activity spec and implementation plan.
- Existing task mirror and PR description.

## Test plan

Inspect current decoder and bridge interfaces, validate document consistency and relative links, and define implementation regression cases. No runtime code changes.

## Acceptance

Explicit policy ownership, bounded decoder memory with honest validation tradeoffs, named loss attributes and delivery ownership, and a freshness policy that cannot confuse replay with live evidence.

## Outcome

- **Actual files:** spec, plan, task mirror and this ledger; PR description aligned.
- **Commits:** docs: define activity policy and address logging review findings; Refs: OME-887.
- **Gates:** source inspection, independent Standards/Spec review, relative document links and diff hygiene. Clarified observation-age evidence for delayed ordinary delivery as well as replay. No product code changed.
- **Deviations:** freshness timeout remains proposed at 180 seconds pending the owner answer. Bounded ID uniqueness validation and the fresh-observation evidence mechanism remain explicit implementation-readiness review gates; no implementation authorized.
