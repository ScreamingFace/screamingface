---
id: OME-1942
linear_url: https://linear.app/openmined/issue/OME-1942/a-url4-pdf-reaches-openai-models-with-no-filename-so-the-model-never
status: in_review
type: bug
priority: high
labels: [bug, screamingface-engine, agentic]
parent: OME-1529
created: 2026-11-17
closed:
---

# A url4 PDF reaches OpenAI models with no filename

Every file part the engine sends now carries a filename: the attachment's own, else `attachment.<ext>` from its media type (`attachment.pdf`). Before, a url4 `src=` PDF had none and OpenAI models ignored it while still answering.

Ledger: `../work/2026-11-17-pdf-filename.md`.
