---
ticket: OME-1126
stack: screamingface-engine
status: done
started: 2026-09-08
finished: 2026-09-08
---

# OME-1126 — a reasoning-only model reply is not a broken gateway

## Intent

The live-run hunt (OME-1126 issue comment, 2026-09-08) showed a healthy `stop` response
with `content: null` and the text in `reasoning_content` being classified as
`aigateway_bad_response` ("malformed aigateway response", permanent) — wrong component
(the gateway was fine), and a diagnostic dead end because the message carries no detail
and the report sanitizer (`_public_message`) replaces any path-bearing message with a
canned default. Two truths must survive to the report: WHO misbehaved (the model, not
the gateway) and WHAT the response looked like (finish_reason, whether reasoning text
was present) — phrased sanitizer-safe (no slashes, ≤200 chars). The transport-death
half of the misclassification stays with OME-1127; this unit covers only the
complete-response, reasoning-only shape.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner/model_response.py` —
  `parse_choice` captures `reasoning_content`; `raise_if_unusable` classifies a
  content-less choice that DID carry reasoning text as `model_empty_content` with a
  sanitizer-safe diagnostic message; the no-reasoning fallback keeps
  `aigateway_bad_response` but names the finish_reason.
- `apps/screamingface-engine/tests/unit/test_reasoning_only_choice.py` — NEW.

## Test plan

- RED: a `stop` choice with `content: null` + `reasoning_content` text raises
  `model_empty_content`, message names the model behavior and finish_reason, and
  survives `_public_message` unchanged.
- Boundary: content `null`, no reasoning → still `aigateway_bad_response` (regression
  pin for the existing taxonomy); refusal and token-cap classifications unchanged.
- The message contains no `/` and fits 200 chars (the sanitizer's replacement rules).

## Acceptance

- New tests pass; every existing test passes unmodified.
- `run_gates.py screamingface-engine` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** (filled by the commit step)
- **Gates:** run_gates.py screamingface-engine — ALL GATES GREEN (2428 passed, 5
  skipped).
- **Deviations:** none. The transport-death misclassification and failure-metadata
  payload preservation stay with OME-1127/OME-784 as planned.
