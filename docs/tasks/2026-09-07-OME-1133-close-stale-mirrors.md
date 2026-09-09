---
id: OME-1133
linear_url: https://linear.app/openmined/issue/OME-1133/close-the-five-stale-docstasks-mirrors-and-work-ledgers-from-the
status: done
type: task
priority: 3
labels: [repo, agentic, autonomous, task]
created: 2026-09-07
closed: 2026-09-07
---

# Close the five stale docs/tasks mirrors and work ledgers

`OME-967`, `OME-990`, `OME-1074`, `OME-1105` and `OME-1121` all shipped and are Done in
Linear, but their mirrors and ledgers still read `status: in_progress`. Linear is the status
authority and the mirror is its repo-side reflection — so a reader with only the checkout saw
five observability items apparently still in flight while Phase 1 was being built on top of
them.

Frontmatter only: `status: done` plus the PR's merge date in `finished:`/`closed:`. Prose and
ledger Outcome sections are untouched.

The underlying process defect — the mirror close belongs in the shipping PR and was missed
five consecutive times — is recorded in the Linear issue. Enforcing it mechanically is
deliberately **not** in scope: `run_gates.py` cannot see Linear state, so where that check
lives is its own decision.

Ledger: `docs/work/2026-09-07-OME-1133-close-stale-mirrors.md`
