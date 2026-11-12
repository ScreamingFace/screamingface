---
id: OME-1862
linear_url: https://linear.app/openmined/issue/OME-1862/add-a-partial-grading-failures-section-to-the-fusions-guide
status: In Progress
type: task
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1313
created: 2026-11-10
closed:
---

# Add a partial grading failures section to the Fusions guide

Extend the SF Client Fusions guide (`public-docs/src/pages/sf-client/guides/FusionsPage.vue`)
with a dedicated "Handle partial grading failures" section before the `sf.Fusion` shortcut:
`quorum` on `sf.Fanout` sets how many members must succeed, and a member built with
`optional=True` may fail without stopping the fusion. Includes a runnable example (output is the
real `repr()`) and the existing `sf-client-0-1-11-fusion-quorum` diagram via `ThemedDiagram`. The
buried one-line quorum mention in section 3 is folded in; the shortcut is renumbered to 6.

Sibling of OME-1842 (map-reduce / compose guide polish). Quorum diagram assets and the
`docs/diagrams` mirror were already on `origin/main`.

Branch: `OME-1862-fusions-guide-partial-failures`.
Ledger: `docs/work/2026-11-10-fusions-guide-partial-failures.md`.
