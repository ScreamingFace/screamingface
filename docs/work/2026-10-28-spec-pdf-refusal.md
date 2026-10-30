---
ticket: OME-1760
stack: repo
status: done
started: 2026-10-28
finished: 2026-10-28
---

# spec-pdf-refusal — resolve the PDF-on-file-blind-model contradiction in spec #1450

## Intent

The merged file-input spec contradicted itself: the Ollama gateway note said "PDF-to-text for Ollama stays
with `OME-1550`", while §3 item 4 says a model that cannot take a file is never degraded silently. Owner decisions
(Sergey, 2026-10-28/29): a typed refusal at gateway dispatch (`unsupported_content_part` → url4 `intent_error`);
no PDF-to-text fallback in v1.

## Planned changes

- `docs/spec/2026-10-16-OME-1535-file-input-execution.md`: replace the "PDF-to-text for Ollama stays with
  `OME-1550`" sentence with the refusal rule and a pointer to §3 item 4 and §4.

## Test plan

Docs only. Check that no other line of the spec still promises PDF-to-text.

## Acceptance

- The spec has one rule for a PDF sent to a file-blind model: a named refusal.

## Outcome

- Changed one sentence in the gateway findings; §3 item 4 and §4 unchanged.
- Implementation is pending: #1588 (`OME-1545`, draft, `db6b228ec`) reports the gateway's
  `unsupported_content_part` as url4 `intent_error`.
- Review round 1 (HupBaHa, 2026-10-29): the v1 guarantee is a typed provider refusal at gateway dispatch, not a
  model-name admission check (C9 is image-only), so the C9/model-name claim was removed (owner decision). OME-1550's
  Linear description, OME-1641 and `docs/spec/2026-10-16-ollama-file-parts.md` were updated so no record still
  hands PDF-to-text to OME-1550.
- Deviations: none.
