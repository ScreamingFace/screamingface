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
- Review round 2 (Khoa, 2026-11-02; owner decision, Sergey): adopting Khoa's review, v1 refuses a PDF sent to a
  model that cannot read PDFs **at engine run admission**, keyed on the model's published `/v1/models`
  `input_modalities` containing `pdf` (`G/core/model_capabilities.py`, #1451; the list the engine already reads for
  pictures). The gateway's `unsupported_content_part` → url4 `intent_error` (422) stays as the **backstop**. This
  supersedes the round-1 / 2026-10-28 wording that made the gateway refusal the v1 guarantee. Reasons: only Ollama
  refuses at the gateway today, while OpenAI, Anthropic and OpenRouter pass PDFs through, so a PDF to a text-only
  model such as `o3-mini` would still reach the provider; and in a Fusion, refusing at admission avoids paying the
  other members before the blind one fails. It is still not a model-name check (the source is the published
  modalities), which answers HupBaHa's round-1 objection that C9 is image-only. Changed: the §1 gateway note and
  the pass-through bullet, §3 item 4, the §4 `intent_error` row, the `OME-1537` open item, and the Ollama spec's
  out-of-scope note. No ticket owns the PDF admission check yet (`OME-1548` is pictures only; `OME-1681` tracks the
  PDF row): follow-up ticket to be filed. "No PDF-to-text in v1" and "`OME-1550` is office formats only" are kept.
- Deviations: none.
