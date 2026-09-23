---
id: OME-1272
linear_url: https://linear.app/openmined/issue/OME-1272/a-system-message-with-placeholders-would-bake-wrong-text-without-any
status: backlog
type: bug
priority: P3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-23
closed:
---

# A system message with placeholders would bake wrong text without any flag

The system-message-as-leading-input-text seam (PR #1018) conserves only the
`template` argument; inspect's `system_message(template, **params)` also
substitutes `{placeholders}` from params/metadata/store. An eval using any of
those would bake its raw template unflagged. hellaswag verified unaffected —
latent gap. Close it at introspection: params or placeholder syntax must
reproduce-or-refuse, never bind the bare template.
