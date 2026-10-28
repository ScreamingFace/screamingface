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
while §3 item 4 refuses a file-blind model by name (`intent_error`). Owner decision 2026-10-28: refuse by
name; `OME-1550` covers office formats only.

Parent epic `OME-1529`. Ledger: `../work/2026-10-28-spec-pdf-refusal.md`.
