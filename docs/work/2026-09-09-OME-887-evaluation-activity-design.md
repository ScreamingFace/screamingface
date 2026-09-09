---
ticket: OME-887
stack: repo
status: completed
started: 2026-09-09
finished: 2026-09-09
---

# OME-887 — Design useful evaluation activity

## Intent

Prepare a clean, reviewable contract and delivery plan for major-stage evaluation activity: case loading, answering, grading, aggregation and final evaluation outcomes. User requested full-stage coverage with detailed facts and a calm default view. This is design preparation only; implementation policy and new delivery tickets await owner review.

## Planned changes

- docs/spec/2026-09-09-OME-887-evaluation-activity.md
- docs/plan/2026-09-09-OME-887-evaluation-activity.md
- docs/tasks/2026-09-09-OME-887-live-evaluation-activity.md

## Test plan

Validate the design against actual current Engine/URL4/Client interfaces, merged PRs 877/884, and existing issue ownership. Check relative document links, changed-file scope and git diff hygiene. Specify implementation acceptance tests without modifying code or existing tests.

## Acceptance

One proposed versioned activity contract, explicit producer ownership, no benchmark knowledge in generic Runner/URL4, truthful handling of overlap/unknown identity/drop/cancellation, concrete proposed bounds, and staged Engine/Client delivery with no competing score or result authority. Surface unresolved decisions rather than imply approval.

## Outcome

Prepared the proposed spec, delivery plan and task-mirror links. Independent Standards and Spec reviews found no architectural blocker; addressed Candidate outcome placement, an explicit prepared-task count and precise bounded suppression snapshot semantics. Relative document links and `git diff --check` pass. No product code or tests changed; implementation gates are specified for the later units. Schema, limits and delivery scope remain proposed pending owner review. OME-887 remains open; completing this design preparation does not complete delivery.
