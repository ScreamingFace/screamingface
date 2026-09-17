---
ticket: OME-941
stack: screamingface-engine
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-941 — Surface TerminatedData.error and trace_id on the engine HTTP GET path

## Intent

`_terminal_response` in `rest/routes.py` maps a run's terminal frame to HTTP using only
`terminated.data.status`, through a fixed three-entry problem table. `TerminatedData.error`
(`code` / `message` / `permanent`) is never read, so a synchronous HTTP caller of `GET /` gets a
bare `502 "the run failed"` while the real diagnosis sat on the stream that is about to be purged.
The run's `trace_id` is likewise never surfaced, so the caller cannot join the failure to anything
in the trace store — which is the whole point of the Phase 0 traceability epic (`OME-935`).

This unit surfaces the error detail **and** the trace id on the problem response, under a
sanitisation rule strict enough that a provider-authored string can never reach the wire.

## Design decisions

1. **One allowlist governs BOTH the code and the message.** `ErrorInfo.code` comes from
   `url4.streaming.lifecycle._error_info`, which reads `getattr(exc, "code")` off whatever
   exception ended the run — an arbitrary string authored anywhere in the executor or an adapter.
   `ErrorInfo.message` is `str(exc)`, which for any provider-facing adapter carries provider text
   verbatim. So: a closed set `_ENGINE_ERROR_CODES` of engine-authored codes. Code on the list →
   code and message are echoed. Code off the list (or absent) → the code collapses to
   `internal_error` and the message is **dropped entirely**, falling back to the existing table
   detail. Two separate lists (echo-code-but-not-message) were considered and rejected: the
   ticket's rule is "assume `message` is tainted unless the code is on your allowlist", and a
   single list is the version that cannot drift out of step with itself.
2. **What is on the allowlist.** Only codes whose message is authored by url4 core or the engine's
   own control plane, about the *caller's own expression* or the engine's own limits:
   `malformed_source`, `unbound_reference`, `cycle_detected`, `unrenderable`,
   `expansion_not_iterable`, `unknown_identity`, `unknown_processor`, `timeout`,
   `result_too_large`. Deliberately **excluded**: `resolution_failed` (I/O layer — the message can
   embed a remote body), `internal_error` (message is `str()` of an arbitrary exception), and
   every `aigateway_*` / `provider_refusal` / `model_*` / `judge_*` / `*_grading_failed` code,
   all of which are provider-adjacent by construction.
3. **`permanent` always rides along when an error frame exists.** It is a bool, not text: it
   cannot carry a leak, and it is the one field that tells the caller whether a retry can ever
   succeed. It is therefore reported even for a scrubbed error.
4. **`trace_id` is safe to disclose and is NOT the topic.** The topic is a 64-char
   `secrets.choice` capability (`auth/token.py`); the trace id is an independent
   `secrets.token_hex(16)` (or the caller's own inbound one) minted in `lifecycle.run`. It is
   parsed out of the terminal frame's `traceparent` with the existing
   `url4.streaming.trace.parse_traceparent`, which also rejects malformed and all-zero values, so
   a junk `traceparent` yields no field rather than a junk field. The topic is never rendered.
5. **Extension members, not a restructured body.** `Problem` gains three optional members
   (`code`, `permanent`, `trace_id`), which RFC 9457 §3.2 explicitly allows and which
   `exclude_none=True` already drops when absent — so every existing problem response stays
   byte-identical.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/auth/problem.py` — three optional extension
  members on `Problem`, and the matching kwargs on `ProblemException.__init__`.
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` — `_ENGINE_ERROR_CODES`, a
  `_sanitized_error` helper, and `_terminal_response` reading `terminated.data.error` and
  `terminated.traceparent`.
- `apps/screamingface-engine/tests/unit/test_terminal_error_detail.py` — new test file
  (test files are append-only; `test_rest.py`'s `_terminated` helper takes no error and is not
  touched).

## Test plan (RED first)

- A failed run whose error carries an allowlisted code names that code, its message, and the
  run's trace id on the 502 — not just "the run failed".
- **Security:** a failed run whose error carries a provider-authored code and a provider-authored
  message (an API key, a provider body) reaches the HTTP response with *neither* — the code is
  `internal_error`, the message appears nowhere in the raw response bytes, and the fallback
  detail is the table's. Asserted over the decoded JSON fields and over `resp.content`, never
  over a `repr()`.
- The topic appears nowhere in a terminal problem response.
- `permanent` is reported for a scrubbed error as well as an allowlisted one.
- A `timed_out` run surfaces its error detail on the 504 too (the path is status-independent).
- A malformed `traceparent` yields no `trace_id` member rather than a junk one.
- A terminal frame with no error at all keeps the pre-existing response exactly.

## Acceptance

- `uv run .claude/scripts/run_gates.py screamingface-engine` green.
- Every new behaviour killed by a mutation of its production line.

## Outcome

- **Actual files:** as planned — `auth/problem.py` (three optional RFC 9457 extension members +
  the matching `ProblemException` kwargs), `rest/routes.py` (`_ENGINE_ERROR_CODES`,
  `_sanitized_error`, `_terminal_response` reading `data.error` and `traceparent`), and the new
  `tests/unit/test_terminal_error_detail.py` (9 tests). No prior test was touched; the
  append-only gate confirms it.
- **Commits:** see the branch `OME-941-terminal-error-detail`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine` — ALL GATES GREEN
  (append-only check, ruff check, ruff format, pyright, layering, pytest with coverage ≥80).
- **Mutation testing:** 10 mutations applied to the production lines this unit added, 10 killed.
  The two that matter most: making `_sanitized_error` pass every message through, and making it
  pass the unvouched code through, both die on
  `test_a_provider_authored_message_never_reaches_the_http_response`. Substituting the topic for
  the trace id kills 8 of 9. No assertion in the new file is taken over a `repr()` — the leak
  checks walk the decoded JSON members and then `resp.content`, which is the failure mode that
  let a previous security test in this repo pass against a live leak.
- **Deviations:** none from the plan. Two tests beyond it, both cheap and both killing a real
  mutation: an all-zero trace id is not reported (W3C's invalid value would otherwise look like
  a searchable run), and a run that terminated without an error still reports its trace id.
