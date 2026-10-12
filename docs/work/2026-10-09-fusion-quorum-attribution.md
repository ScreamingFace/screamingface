---
ticket: OME-1557
stack: screamingface-engine
status: done
started: 2026-10-09
finished: 2026-10-09
---

# Fusion quorum attribution correction

## Intent

Fix the user-approved PR #1340 review finding: a failed optional member is credited
with another member's successful answer in scored benchmark artifacts.

## Planned changes

- Engine operation output attribution and a new focused unit-test module.
- A Client-generated duplicate-member candidate fixture and an appended
  FrontierScience lifecycle regression.
- This ledger, specification, and plan.

## Test plan

Demonstrate failure before production edits. Cover direct optional sources,
optional composite members, repeated identical calls, unique fingerprints, and
actual gateway request contents plus scored operation artifacts. Run Engine gates.

## Acceptance

- An optional failed member never borrows a sibling's output or finish reason.
- Ambiguous optional fingerprints remain null even after repeated identical calls.
- Unique fingerprints retain outputs/accounting and existing required-only sharing
  remains unchanged. No old assertions change and no paid calls run.

## Outcome

- **Actual files:** the Engine attribution module, new focused test module,
  appended FrontierScience lifecycle checks, Client-generated fixture, spec,
  plan, and this ledger, as planned.
- **Commit:** `fix(engine): keep optional shared member outputs unknown`, on
  reviewed parent `0397d88e90f1411a0d43ec70de37b2dc13e0d056`.
- **Regression evidence:** six unit cases and both FrontierScience variants failed
  against the original attribution logic after fixture setup was corrected;
  all 43 focused checks pass with the fix. The original review reproduction and
  its standalone regression also pass: the Case is scored, ambiguous members
  have null output/finish reason, and synthesis retains its answer/accounting.
- **Gates:** `PYTEST_XDIST_AUTO_NUM_WORKERS=4 UV_OFFLINE=1 uv run
  .claude/scripts/run_gates.py screamingface-engine --base HEAD` passed all
  append-only, lint, format, typecheck, layering, and full coverage-suite gates.
  Installed both Engine extras; coverage is 94.20% against the 80% floor.
- **Wisdom:** conservative null attribution avoids inventing evidence, including
  when retries produce more calls than claimants. Unique-binding accounting and
  required-only sharing remain unchanged. No new request identity, retained
  prompts, public API, wire shape, dependencies, or execution behavior.
- **Deviations:** used an isolated worktree on the existing PR head. No existing
  assertions changed. No paid calls or external messages. The existing OME-1557
  issue and PR own this follow-up; do not close the issue before PR completion.
