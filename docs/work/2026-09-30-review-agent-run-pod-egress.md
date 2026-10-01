---
ticket: none (owner waived a ticket for review-agent changes, 2026-09-30)
stack: repo
status: done
started: 2026-09-30
finished: 2026-09-30
---

# review-agent-run-pod-egress — teach the review agent that Engine run pods have no internet

## Intent

The review agent said the engine's Helm chart lacking a NetworkPolicy was a "standing gap",
which reads as "the Engine has open egress". The infrastructure repo shows the opposite: the
platform puts a default-deny on the engine's namespace, and run pods reach only DNS, the AI
gateway and in-cluster services in dev, staging and prod. This unit corrects that line and adds
the review checks that follow from it.

## Planned changes

- `.claude/agents/sf-code-review.md`: Lane 4 line corrected; one Lane 6 bullet added.
- This ledger.

## Test plan

- Docs only. Every infrastructure claim links to a file and line range pinned at infrastructure
  commit `9f513d769731fbe1deec112c104be0ac616487da`.

## Acceptance

- The owner reviews the PR.

## Outcome

- **Actual files:** `.claude/agents/sf-code-review.md`, this ledger.
- **Commits:** one `docs(repo)` commit on `review-agent-run-pod-egress`.
- **Gates:** docs only, no code gates.
- **Deviations:** no Linear ticket or task mirror, per the owner's waiver for review-agent changes.
