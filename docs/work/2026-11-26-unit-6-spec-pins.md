---
ticket: OME-2047
stack: repo
status: in_progress
started: 2026-11-26
finished:
---

# Router Unit 6 contract pins

## Intent

Pin standalone Router delivery contracts on `99072d273706f5ac673d49f5cd605a763e66c220`, and
enumerate the decisions still required before implementing any affected interface.

## Planned changes

- Amend `docs/spec/2026-11-16-router-recipe-extension/{00-overview,contracts,contracts-replay,contracts-entry,test-plan}.md`.
- Keep the C4 panel boundary consistent across the spec and its acceptance matrix.

## Test plan

- Verify the exact base, prior-test blob inventory, diff and Markdown structure; run repo gates.
- Specify reader/writer compatibility and failure witnesses without changing executable tests.

## Acceptance

- Each affected leaf has a pinned contract or a named hold with evidence to clear it. Wire,
  storage, runtime, result readership, activation and rollback remain separately testable.

## Outcome

- **Actual files:** The five planned spec files and this ledger.
- **Commits:** None; the exact amendment remains a draft pending owner approval.
- **Checks:** Repo gates, diff whitespace, Markdown tables, links, anchors and fences passed.
  Reconciled the collision set and verified the 16 prior-test inventory blobs against the
  pinned base. No executable tests changed or runtime suite run.
- **Deviations:** None. The rendered panel goldens, coordinated integration bases, prepared-input
  decision, measured root admission limit and exact transition approvals are still required
  before the affected implementation leaves.

### Review follow-up

- Aligned C9 with the Gateway replay renderer and the Engine economics reader. A recorded error
  keeps its detail and supported headers and has an explicit null price reference.
- Moved panel execution, synthesizer attempts and inline envelope spoof coverage to Unit 6.
  Preserved Unit 5.2's pure decisions, shared observer, static literal-route test and terminal
  spoof coverage. Updated the overview to the landed proof and contract history.
- Refreshed the named C9/C15/C16 implementation anchors on the pinned base and rechecked the
  open integration dependencies and 16 prior-test inventory blobs. Repo and Markdown checks
  passed. The outstanding interface and activation holds remain in force.

### C9 run-manifest reference follow-up

- Corrected six source references at the pinned base: `run_expression_scope` and its call site,
  `seal_frozen_copy`, `Provenance`, `FrozenCopyStore.seal`, `FrozenCopy.provenance`, and the capture
  branch of `_evaluate_in_copy`. The C9 contract text and the other specification files are unchanged
  apart from these references. Verified the source ranges, candidate fingerprints, Markdown and
  repository gates.
