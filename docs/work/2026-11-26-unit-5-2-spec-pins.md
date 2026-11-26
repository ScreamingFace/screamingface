---
ticket: OME-2043
stack: repo
status: in_progress
started: 2026-11-26
finished:
---

# Unit 5.2 routing contract pins

## Intent

Prepare the Unit 5.2 contract amendment for review before Engine implementation.

## Planned changes

- Amend `docs/spec/2026-11-16-router-recipe-extension/00-overview.md`, `contracts.md`,
  `contracts-entry.md`, `contracts-replay.md` and `test-plan.md` for Unit 5.2 only.

## Test plan

- Check links, table structure and diff whitespace. Specify the future contract and regression
  tests in the shared test plan; the amendment does not implement them.

## Acceptance

- The draft pins profile input, policy, decision identity, attempt evidence and classifier discovery
  while preserving the shipped fixed-profile behavior. The owner approval gate is explicit.

## Outcome

- **Actual files:** Five shared specification files, as planned, plus this ledger.
- **Base:** `1cb41a12e58efab99146ab2e764b6203aefcf9f6`.
- **Commits:** this PR; one conventional docs commit referencing OME-2043.
- **Checks:** repo gates, diff whitespace, relative links, heading anchors, table widths and fenced
  blocks. Focused Engine routing/provenance tests corroborate the pinned source behavior. No
  executable or test files changed.
- **Deviations:** Two independent reviews found bounded strict-record and source-provenance
  contradictions. The corrected candidate carries ADMIT permanence, current C11 reserved-code
  semantics and explicit `max_tokens` preflight wording. The Unit 5.1 SDK runtime proof is now
  merged as PR #2077.
