---
id: OME-1769
linear_url: https://linear.app/openmined/issue/OME-1769/make-pinned-cache-capture-opt-in-capturefalse-by-default
status: in_review
type: task
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1307
created: 2026-10-29
---

# Make pinned-cache capture opt-in (capture=False by default)

`sf.evaluate`, `Client.evaluate` and `AsyncClient.evaluate` capture a pinned cache only when the
caller passes `capture=True`. This reverses Q22 (decision Q31 in
`docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md`). A replay still never
captures. The Engine and AIGateway do not change.

- 2026-10-29: filed, implemented, PR opened.
