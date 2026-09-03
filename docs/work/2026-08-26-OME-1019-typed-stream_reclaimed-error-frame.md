---
ticket: OME-1019
stack: repo
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1019 — Typed stream_reclaimed error frame

## Intent

Give a reconnecting client a typed answer when the Run's stream is gone. Today an attach
to a reclaimed stream is silently RECREATED empty and the client heartbeats forever —
indistinguishable from a transient failure. R4's reconnect loop needs "reclaimed" to be
final and distinct from "retry".

## Planned changes

- `packages/url4/src/url4/streaming/interfaces/stream.py` (+`__init__.py`) — new
  `StreamNotFoundError` on the port
- `adapters/jetstream.py` — resume cursor (from_sequence != None) on a missing stream
  raises `StreamNotFoundError` (`stream_info` probe); fresh attach still creates
- `adapters/memory.py` — same rule, parity with the broker adapter
- `ws/bridge.py` — `_on_pump_done` maps `StreamNotFoundError` → `ai.url4.error`
  `code="stream_reclaimed"`; other pump errors stay `stream_failed`

## Test plan

- RED: adapter parity tests (cursor-on-missing raises; fresh attach creates), fake-js
  consumer tests (stream_info probe; bind-without-recreate), bridge test
  (resume attach → one `stream_reclaimed` frame)
- The `test_attach_from_sequence_bounds` conformance contract is updated: cursors are
  legal on an EXISTING stream (ensured first); missing stream + cursor is the new
  reclaimed error

## Acceptance

Full engine + url4 suites green; a resume attach on a reclaimed topic answers
`stream_reclaimed` instead of hanging.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (1 port file + exports, 2 adapters, bridge, 3 test files).
- **Commits:** `a38f06c2` — feat(screamingface-engine): typed stream_reclaimed answer for reclaimed streams
- **Gates:** engine 2059 passed / 5 skipped; url4 1164 passed; full stack gates at epic end
- **Deviations:** the pre-existing `test_attach_from_sequence_bounds` conformance test
  needed its documented precondition updated (ensure the stream before subscribing) —
  the cursor-on-missing behavior is the deliberate change of this issue, and the test now
  documents it.
