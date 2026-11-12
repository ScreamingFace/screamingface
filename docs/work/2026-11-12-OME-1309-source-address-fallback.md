---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-12
finished: 2026-11-12
---

# Try alternate public source addresses after connection failure

## Intent
Improve draft #1749 locally before publication, as requested. The transport currently selects only the first DNS address, which falsely marks a reachable source unchecked if that address is unavailable while another works.

## Planned changes
Try the other already-validated public addresses on connection failure or connection timeout. Keep the existing overall deadline, original Host/TLS identity, no-keepalive transport, and all-address security validation. Do not retry HTTP responses or read failures. No new DNS lookups, dependencies, schema or UI changes.

## Test plan
Reproduce first-address failure with a successful second address. Cover connection errors/timeouts, all addresses unavailable, private answers mixed with public answers, original HTTP/TLS hostname, no retries after HTTP or read errors, and one shared deadline across attempts. Run focused and full scoreboard gates.

## Acceptance
A reachable alternate address avoids a false unchecked result. Unsafe DNS answers prevent all requests. Retries stay inside the original source-check deadline. Existing tests remain unchanged.

## Outcome
- **Confirmed regression:** first-address ConnectError/ConnectTimeout produced False despite a healthy second address. Four new regression cases failed before the fix, then passed.
- **Implementation:** try the remaining already-validated addresses on connection errors/timeouts, preserving Host and TLS identity. Shared source deadline, HTTP/read-error behavior, and all-address security checks remain intact. Updated runbook.
- **Validation:** all 50 focused source/DNS/CLI checks pass, including eight new fallback cases; full scoreboard gate runner passes (format, lint, types, Python suite/coverage, and all registered portal tests). No previous tests changed.
- **Commit:** `fix(scoreboard): try alternate public source addresses` (local only).
- **Wisdom review:** small transport-only change; no dependency, data-model, migration or UI changes. Resolve once per hop, validate every answer before requesting any address, and do not reset the deadline for retries.
- **Publication:** kept local as requested. No push, ready-for-review transition, reviewer request, or Linear post.
