---
ticket: OME-1760
stack: repo
status: done
started: 2026-10-28
finished: 2026-11-02
---

# spec-pdf-refusal — refuse PDFs at admission on models without `pdf` input, no PDF-to-text in v1 (spec #1450)

## Intent

The merged file-input spec contradicted itself: the Ollama gateway note said "PDF-to-text for Ollama stays
with `OME-1550`", while §3 item 4 says a model that cannot take a file is never degraded silently.

**Final rule** (owner, Sergey, 2026-11-02, review round 2): v1 refuses a PDF sent to a model that cannot read
PDFs **at engine run admission**, keyed on the model's published `/v1/models` `input_modalities` containing
`pdf` (not on model names), with url4 `intent_error` naming the model, before any model is paid. The admission
check is tracked by `OME-1803` (not on `main` yet). The gateway's 422 `unsupported_content_part` → url4
`intent_error` is the **backstop** (translation pending in #1588, `OME-1545`). No PDF-to-text fallback in
v1; `OME-1550` covers office formats only.

*Superseded:* the 2026-10-28/29 owner decision made the typed refusal at gateway dispatch the v1 guarantee
(gateway-only policy); review round 2 replaced it with the rule above.

## Planned changes

- `docs/spec/2026-10-16-OME-1535-file-input-execution.md`: state the final rule in the §1 gateway findings,
  §3 item 4 and the §4 error table, and separate it from current-`main` behaviour.
- `docs/spec/2026-10-16-ollama-file-parts.md`: drop the hand-off of PDF-to-text to `OME-1550`.
- *Superseded (2026-10-28 plan):* replace only the "PDF-to-text for Ollama stays with `OME-1550`" sentence
  with the gateway refusal rule.

## Test plan

Docs only. Check that no line of the spec still promises PDF-to-text, and that no line claims the admission
check exists on `main`.

## Acceptance

- The spec has one rule for a PDF sent to a file-blind model: admission refusal on the published `pdf`
  modality, gateway 422 as backstop, never a silent drop.
- The spec says plainly which parts of that rule are pending (`OME-1803`, #1588).

## Outcome

- Summary (final): the spec's §1 gateway findings, §3 item 4 and §4 (`intent_error` and
  `unsupported_content_part` rows) state the final rule above; §1 separates the normative v1 rule from
  current-`main` behaviour. The Ollama spec's out-of-scope note no longer hands PDF-to-text to `OME-1550`.
- Implementation status: nothing of the rule is on `main` yet. Admission check: `OME-1803` (Backlog). Backstop
  translation: #1588 (`OME-1545`, draft). On `main` today only Ollama and configured remote endpoints refuse a
  PDF, with the raw gateway 422.
- *Superseded (round 0, 2026-10-28):* "Changed one sentence in the gateway findings; §3 item 4 and §4
  unchanged." Review round 2 changed §3 item 4 and §4.
- Implementation is pending: #1588 (`OME-1545`, draft, `db6b228ec`) reports the gateway's
  `unsupported_content_part` as url4 `intent_error`.
- *Superseded by round 2:* Review round 1 (HupBaHa, 2026-10-29): the v1 guarantee is a typed provider refusal at gateway dispatch, not a
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
  PDF row), so it was filed as `OME-1803` under `OME-1529` (2026-11-02). "No PDF-to-text in v1" and "`OME-1550` is office formats only" are kept.
- Review round 3 (HupBaHa, 2026-11-02T15:14Z): the spec said the engine "refuses the run at admission" and
  that the check "is implemented by `OME-1803`", but `OME-1803` is Backlog and no admission code has landed.
  Verified against `main` (`834c3086a`): no engine modality read or admission check (pictures included); the
  gateway refuses PDFs only for Ollama (`allow_files=False`) and configured remote endpoints (text-only
  contract); #1588 is still a draft. Changed: §1 now has a normative "v1 rule" bullet and a separate "Current
  `main`" bullet; §3 item 4 and the §4 rows mark the admission check and the translation as pending; the
  resolved `OME-1537` item moved from "Still open" to "Resolved since this snapshot"; "the list the engine
  already reads for pictures" became "the list picture admission is to read"; the Ollama spec and the task
  mirror say the admission check is pending. This ledger's Intent and summary now lead with the final rule;
  superseded lines are marked, not deleted. PR body and title updated.
- Deviations: none.
