---
id: OME-826
linear_url: https://linear.app/openmined/issue/OME-826/fix-pr-571-post-merge-review-findings-money-bug-equality-walker
status: In Progress
type: task
priority: High
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-14
closed:
---

# Fix PR #571 post-merge review findings

Implements all 8 fixes from the adversarially-verified /code-review of PR #571
(OME-786 pipeline composition): the post-paid-run duplicate-display-name money bug,
the `_is_named` structural-equality break, the removed rendered-surface linker guard,
the 3-way duplicate topology walkers, dead `_recipe_kind`/`synthesis_root` machinery,
`then()` re-implementing Pipeline flattening, the per-candidate benchmark re-parse,
and the unclosed OME-786 ledger/mirror.

Ledger: `docs/work/2026-08-14-OME-826-pr571-review-fixes.md`
