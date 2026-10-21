---
id: OME-1641
linear_url: https://linear.app/openmined/issue/OME-1641/ollama-answers-200-with-a-pdf-silently-dropped
status: in_progress
type: bug
priority: high
labels: [bug, aigateway, agentic, autonomous]
created: 2026-10-16
closed:
---

# Ollama answers 200 with a PDF silently dropped

Live check (spike `OME-1598`, 2026-10-16, local `qwen2.5vl:3b`): a PDF to an Ollama model answered
200 with the file gone (+7 prompt tokens, unrelated answer). LiteLLM's `ollama_chat` conversion keeps
only `image_url` parts and discards `file` parts, and the Ollama plugin never ran the `OME-1541`
content gate. Fix: the plugin refuses `file` parts and remote image URLs with 422
`unsupported_content_part`; data-URI images pass. Parent epic `OME-1529`.
Ledger: `../work/2026-10-16-ollama-file-parts.md`.
