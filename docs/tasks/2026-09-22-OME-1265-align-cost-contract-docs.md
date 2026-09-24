---
id: OME-1265
linear_url: https://linear.app/openmined/issue/OME-1265/align-the-ome-822-contract-docs-with-the-expand-phase-that-shipped
status: done
type: task
priority: medium
labels: [scoreboard, agentic, autonomous]
parent: OME-1251
created: 2026-09-22
closed: 2026-09-24
---

# Align the OME-822 contract docs with the expand phase that shipped

Non-blocking review follow-up on PR `#841` (HupBaHa, 2026-09-22). `#841` merged as `99e2d4b2`
implementing the **expand** phase — `run_cost_status` optional, an absent status beside an amount
resolving to `complete`, and omitting both fields **accepted**. Several contract surfaces still
described the final contract that `OME-1258` owns, so a reader would conclude the 422 gate was
already active.

Ledger: `docs/work/2026-09-22-OME-1265-align-cost-contract-docs.md`.

- 2026-09-22: filed after the review. Six surfaces named by the reviewer; a **seventh** found by
  grepping the shipped claims — the `OME-822` ledger's own Intent contradicts its own
  Review-round-2 section 130 lines below. **Gate:** In Progress.
- 2026-09-22: built on `OME-1265-align-cost-contract-docs` from `origin/main` at `99e2d4b2`.
  The governing spec and the task mirror corrected in place; the plan and the `OME-822` ledger
  **marked, not rewritten** — they record what was believed at the time, and erasing that would
  destroy the audit trail the finding is about. Gates ALL GREEN **without**
  `--skip-append-only`, which is the proof it was comment-only. **Gate:** in review.
- 2026-09-24: merged as `61da426d` (PR `#1019`), unreviewed after 40h with no reviewer response;
  docs-only, on the repo's own precedent (`#1014`, `#1008`). Closed in Linear with the full
  deviation record. **Gate:** Done.
