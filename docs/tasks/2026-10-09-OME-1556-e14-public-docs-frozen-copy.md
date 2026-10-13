---
id: OME-1556
linear_url: https://linear.app/openmined/issue/OME-1556/document-e14-frozen-copies-reproduce-and-metadata-edits-in-the-public
status: in_progress
type: task
priority: high
labels: [repo-dev-processes, agentic, autonomous]
created: 2026-10-09
closed:
---

# Document E14 frozen copies, reproduce and metadata edits in the public docs

Parent: OME-1307. 1 PR, in the E14 stack.

Ledger: `docs/work/2026-10-06-e14-c1-docs.md`.
Spec: `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` (binding).

Scope:

- The guides, API pages and caching page describe capture, replay and reproduction from the frozen copy, as the final SDK does.
- The caching page holds the full mechanics. The other pages keep one or two sentences and a link.
- The glossary drops Cache Revision and Reproducible. It adds Frozen Copy, Capture Status and Reproduction.
- The gates are the `public-docs` build and lint.

- 2026-10-09: PR opened on branch `OME-1556-e14-c1-docs`; the docs build and lint pass.
