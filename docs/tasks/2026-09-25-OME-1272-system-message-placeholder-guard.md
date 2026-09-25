---
id: OME-1272
linear_url: https://linear.app/openmined/issue/OME-1272/a-system-message-with-placeholders-would-bake-wrong-text-without-any
status: in_progress
type: task
priority: low
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-09-23
closed:
---

# A system message with placeholders would bake wrong text without any flag

The importer binds an eval's module-level system message as a fact, and the bake delivers the
constant's text verbatim as leading input text (OME-1253). inspect rewrites that text before
sending it when the solver carries params, when the text holds braces (`str.format` with the
sample's metadata and store), or when the template is a file path. Each case would bake a
different exam with every guard green. The fix flags such a solver for review by name and binds
no fact; hellaswag's plain constant keeps binding.

Ledger: `docs/work/2026-09-25-OME-1272-system-message-placeholder-guard.md`.

- 2026-09-25: work started in its own worktree, branched from `upstream/main` `1f1218ee`.
