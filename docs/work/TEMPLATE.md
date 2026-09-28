---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: <stacks[].name from .claude/sdlc.local.md | repo>
status: planned   # planned | in_progress | done | blocked
started: <YYYY-MM-DD>
finished:
---

# <slug> — <one-line unit title>

## Intent

<What this unit changes and why — one paragraph, product-linked.>

## Planned changes

- <exact files to create/modify>

## Test plan

- <the failing tests to write first: happy path, boundaries, error paths, the invariant protected>

## Acceptance

- <observable criteria that close the unit>

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
