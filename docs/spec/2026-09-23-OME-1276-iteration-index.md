# OME-1276 — Native iteration index

Status: implementation and reserved-name policy approved by owner on 2026-09-23.

An iteration binds `$index` to the zero-based ordinal of its selected collection.
Slicing happens first. The index is assigned before scheduling and does not depend on
completion order, retries or failures. Skipped failures do not renumber later rows.
The binding is available in body sources and per-row intent, including nested expressions.
Nested iterations bind their own index; explicitly capture the outer index under another
name before entering a nested iteration. An empty selection has no row index or body calls.
Outside iteration, existing named-reference behavior remains unchanged (including leaving
unbound references verbatim). `$item`, `$N`, escaping and ordinary bindings retain their
existing semantics. Index substitution reuses reference handling, not expression rewriting.

This is an SDK language extension proposal to Part B collection iteration; it is not claimed
as an already-ratified requirement of the upstream design specification. No count binding,
telemetry, benchmark route or application-specific behavior is introduced.

Acceptance: text and AST execution, sliced and unsliced collections, out-of-order completion,
retry/failure modes, nested scopes and capture, empty selections, literal escaping and
compatibility of named references outside iteration. Full URL4 gates must pass.

Inside iteration, `$index` is reserved and takes precedence over a named `index` source, matching `$item`. Outside iteration, `index` remains an ordinary name. Existing expressions relying on a named `index` inside iteration must rename that binding. The index is substituted as decimal text using normal URL4 value serialization; no new arithmetic or field-path semantics.
