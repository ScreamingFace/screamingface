---
id: OME-1996
linear_url: https://linear.app/openmined/issue/OME-1996/let-a-named-url4-expand-source-take-at-most-one-element
status: Done
type: task
priority: high
labels: [url4-sdk, agentic, autonomous]
parent: OME-1306
created: 2026-11-20
closed: 2026-11-23
---

# Let a named url4 expand source take at most one element

Router Recipe extension, the C19 URL4 leaf.

A named `;expand` source can carry `expand.at_most_one=true` after its `;required` or `;optional`
guard, written by `url4.src(..., at_most_one=True)`. Zero elements contribute nothing and no
failure. One element contributes exactly what a plain source holding it contributes, under the
source's own name. Two or more fail the source with `x.expansion_too_many`, like any other source
failure: `;required` and `;optional` apply to it as to any other. Unmarked sources and ordinary
`;expand` keep their bytes and behavior, and a reader that does not know the key ignores it.

One prior test changed in its module docstring only, with the owner-approved transition pinned in
`.claude/test-change-approvals/OME-1996.json`; no test code or assertions changed. No Router code
is part of this landing. No hosted readiness claim.

Spec: `docs/spec/2026-11-16-router-recipe-extension/contracts-placement.md` (C19).
Plan: `docs/plan/2026-11-16-router-recipe-extension.md` §7.
Ledger: `docs/work/2026-11-19-url4-expand-at-most-one.md`.
Branch: `OME-1996-url4-expand-at-most-one`.

Merged [PR #1995](https://github.com/ScreamingFace/screamingface/pull/1995) as `d2431eb83`.
Linear is Done.
