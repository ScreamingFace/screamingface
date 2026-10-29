---
id: OME-1760
linear_url: https://linear.app/openmined/issue/OME-1760/refuse-pdfs-on-file-blind-models-by-name-in-the-file-input-spec-no-pdf
status: in_review
type: docs
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
created: 2026-10-28
closed:
---

# Refuse PDFs on file-blind models by name in the file-input spec (no PDF-to-text in v1)

Resolves a contradiction in spec #1450 (`OME-1535`): the Ollama note promised PDF-to-text via `OME-1550`,
while §3 item 4 says a model is never degraded silently. Owner decisions 2026-10-28/29: v1 gives a typed
refusal at gateway dispatch (`unsupported_content_part` → url4 `intent_error`, pending in #1588), not a
model-name admission check; no PDF-to-text in v1, and `OME-1550` is narrowed to office formats.

Parent epic `OME-1529`. Ledger: `../work/2026-10-28-spec-pdf-refusal.md`.
