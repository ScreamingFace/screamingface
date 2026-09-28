---
ticket: OME-1120
stack: aigateway
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1120 — Join the inbound traceparent to aigateway's log context and echo it

## Intent

Rung 4b — the payoff rung, and the last one. `OME-1119` put the client's trace id on the wire
to aigateway; `OME-938` gave aigateway a per-request log context and a `%(call_context)s`
render slot. This joins the two: the inbound `traceparent` becomes a field on every aigateway
log line, so one id is greppable across the engine's namespace and `sf-aigw`.

That join IS Phase 1's acceptance (`docs/plan/2026-09-04-OME-1118-*` row 5). Nothing else is
outstanding for the goal.

## Design decisions

**D1 — the W3C rule is mirrored locally, not imported.** `apps/aigateway` does not depend on
`url4` and must not gain a distribution dependency for a 6-line regex. `packages/screamingface`
made the same call in `OME-967`. The rule copied is url4's `_TRACEPARENT_RE` plus its two
all-zero rejections, so all three services agree on what a valid traceparent is; the tests
restate the rejection table rather than importing it, which is what makes a future divergence
show up as a failure instead of being adopted silently.

**D2 — the inbound header is UNTRUSTED input.** A caller controls it. Adopting a malformed or
attacker-chosen value would hand the caller the correlation key for other people's requests.
Invalid → mint a fresh id, the same restart rule the engine applies at its own edge. Nine
rejection cases are pinned: all-zero trace, all-zero span, version `01`, uppercase hex, empty,
absent, wrong field count, short trace id, short span id.

**D3 — the id is bound in the SAME middleware that mints `gateway_call_id`.** One scope, one
place, one lifetime. A second middleware would double the ordering questions
(`add_middleware` inserts at 0, so the last registration is outermost — already a footgun
commented in `main.py`) for no gain.

**D4 — rendered through the existing `parts` list in `CallContextFilter`.** `OME-938` left that
as a list with an AIDEV-NOTE saying this unit adds `trace_id` beside the call id. No new
mechanism.

**D5 — echoed in the response body under `_aigw`, and as a response header.** The body is how a
JSON caller learns the id; the header is how a STREAMING caller learns it, since an SSE
consumer never sees a body object. Both matter: the engine's model calls are streaming.

## Out of scope, restated because the issue asks for it

The issue says "emit it as a **field**, not inside a message string… this distinction decides
whether the phase delivers a filter or a grep." With aigateway's plain-text formatter, a field
on the record renders as `trace_id=<id>` inside the line — **full-text searchable in SigNoz,
not a filterable attribute**. Making it a real attribute means JSON logs, which is a cross-app
migration (engine + aigateway + scoreboard + collector config) deliberately excluded from
`OME-938` for the same reason. This unit delivers the phase's stated payoff — "one trace_id
greppable across every pod's logs" — and the ceiling stays a recorded decision.

## Planned changes

- `src/aigateway/w3c_trace.py` (new) — the shape rule, mirrored from url4.
- `src/aigateway/call_context.py` — a `trace_id` alongside the call id in the same scope.
- `src/aigateway/logs.py` — render `trace_id=` in `CallContextFilter`'s parts.
- `src/aigateway/middleware/call_id.py` — read, validate, adopt-or-mint, bind; echo the header.
- `src/aigateway/plugins/taxonomy/render.py` — `trace_id` in the `_aigw` subtree.
- Tests as below.

## Test plan

RED first:

- The inbound trace id appears on **every** log line of that request, beside the call id.
- **The nine-case rejection table**: each malformed value is replaced by a freshly minted id,
  never adopted and never propagated verbatim.
- A caller cannot displace another request's id — two concurrent requests keep their own.
- Absent header → a minted id, not a missing field and not an all-zero one.
- The response body's `_aigw.trace_id` equals the id on the log lines.
- A streaming response carries the id as a header.
- Rung 4b flips green; **its strict xfail marker is deleted in this PR**.

## Acceptance

- One id spans client → engine → gateway logs; all five ladder rungs green.
- `run_gates.py aigateway` green incl. the auth-surface coverage job.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the published schema — `w3c_trace.py` (new),
  `call_context.py`, `logs.py`, `middleware/call_id.py`, `plugins/taxonomy/render.py`,
  `plugins/taxonomy/session.py`, `usage_accounting.schema.json`,
  `tests/unit/test_trace_context.py` (41 tests), one prior test, and the ladder.
- **Commits:** `feat(aigateway): join the inbound traceparent to the log context` (sha at
  squash-merge).
- **Gates:** `run_gates.py aigateway --skip-append-only` — **ALL GREEN**: **4208 passed**.
  `run_gates.py screamingface --skip-append-only` — **ALL GREEN**.
  **The ladder: 5 passed, 0 xfailed — every rung green, Phase 1's local acceptance in full.**
- **Deviations:**
  - **A published JSON schema changed, which is more than a test edit.**
    `usage_accounting.schema.json` (`$id: https://screamingface.ai/schemas/aigw-usage-accounting.json`)
    declares `"additionalProperties": false`, so echoing `_aigw.trace_id` — which the issue
    asks for explicitly — is a **public response-contract change**. Added to `properties` but
    deliberately NOT to `required`, so a payload from an older gateway still validates.
    `test_the_legacy_header_does_not_change_accounting` pins the exact top-level key set on
    purpose, precisely so a new key has to be deliberate; it was updated to match.
  - **`trace_id` sits at the `_aigw` TOP level, not inside `usage_accounting`.** The trace is
    not an accounting fact, and that object's schema fixes its required keys — putting it there
    would change a published sub-schema for a field unrelated to usage.
  - **A response HEADER was added alongside the body field** (`x-aigw-trace-id`). The issue
    asks for it and the reason is load-bearing: an SSE consumer never sees a response body
    object, and streaming is most of what this gateway serves — so the body field alone would
    leave the majority of callers unable to read their own trace id.
  - **The rejection table is restated, not imported.** `apps/aigateway` has no `url4`
    dependency, so the W3C rule now lives in three places (url4, the client's ladder regex,
    here). Each copy asserts its own rejection table, which is what makes a future divergence
    fail a test rather than be adopted silently.
  - `logs.rendered_context()` was added as a typed accessor for the same reason `OME-938` added
    `record_call_id` — `LogRecord` has no such attribute in its type, so a direct read is a
    pyright error at every site. No `type: ignore` was used.
  - Ladder counts: tests 5 → 5, assertions 15 → 15, xfail markers 6 → 4 (the last two).
