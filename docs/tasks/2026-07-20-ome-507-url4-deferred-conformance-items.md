---
id: OME-507
linear_url: https://linear.app/openmined/issue/OME-507
status: done
type: Improvement
priority: P3
labels: [url4-engine, deferred, agentic]
created: 2026-07-20
closed: 2026-07-20
---

# OME-507 — Deferred conformance items

Split out of `OME-504`: `q=` ordering/mandatoriness, `path`/`port` parse-time charsets, and
`param-key`/`param-value` validation. Each changes wire behaviour or depends on an
unresolved design question rather than being a plain character-class fix.

`param-key`/`param-value` is blocked on `OME-506`: `nested-param-value` admits a
`processor-value`, which may be a full expression and can never satisfy `param-value`'s
character class.

**Owner action:** the `pkg/url4-python-sdk` landing label failed to attach via the CLI
(label lookup error, though it attached fine on `OME-501`..`OME-506` minutes earlier). Add
it in the Linear UI. Parent epic: `OME-500`.
