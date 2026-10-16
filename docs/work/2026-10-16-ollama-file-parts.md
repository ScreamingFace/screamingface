---
ticket: unfiled   # bug leaf under OME-1529, filed at PR-open
stack: aigateway
status: in_progress
started: 2026-10-16
finished:
---

# ollama-file-parts — refuse file parts on Ollama instead of dropping them

## Intent

Live check (spike `OME-1598`, 2026-10-16): a PDF sent to an Ollama model answers 200 with the file
silently gone (+7 prompt tokens, unrelated answer). LiteLLM's `ollama_chat` conversion carries only
`image_url` parts (`extract_images_from_message`) and discards `file` parts, and the Ollama plugin
does not run the `OME-1541` content gate. Make Ollama refuse what it cannot carry with the same typed
422 `unsupported_content_part`. Spec: `docs/spec/2026-10-16-ollama-file-parts.md`.

## Planned changes

- `apps/aigateway/src/aigateway/core/content_parts.py` — `check_messages(..., allow_files=True)`
- `apps/aigateway/src/aigateway/plugins/ollama_provider/plugin.py` — run the gate in `prepare_chat_body`
- `apps/aigateway/tests/unit/test_ollama_content_parts.py` (new)

## Test plan

See `docs/plan/2026-10-16-ollama-file-parts.md`.

## Acceptance

- A `file` part to Ollama → 422 `unsupported_content_part` (`part_type: file`), before dispatch.
- A remote `image_url` to Ollama → 422 (`reason: remote_url`).
- Data-URI images in any role and text-only requests pass unchanged.
- Gemini, Antigravity and Codex behaviour unchanged (default `allow_files=True`).
- `run_gates.py aigateway` green; live re-run: Ollama PDF → 422, image still 4827.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `core/content_parts.py` (`allow_files`, default `True`),
  `plugins/ollama_provider/plugin.py` (gate in `prepare_chat_body`), new
  `tests/unit/ollama/test_ollama_content_parts.py` (10 tests incl. the real route).
- **Commits:** see the branch (`fix(aigateway): refuse file parts on Ollama instead of dropping them`).
- **Gates:** `run_gates.py aigateway` → ALL GATES GREEN.
- **Live (2026-10-16, local `qwen2.5vl:3b`):** before — PDF 200, +7 prompt tokens, unrelated answer;
  after — PDF 422 `unsupported_content_part` (`part_type: file`, `reason: files_unsupported`);
  image still 200 `4827` (+68); text unchanged.
- **Deviations:** none.
