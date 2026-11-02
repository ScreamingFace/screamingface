# Plan — Ollama refuses file parts

Spec: `docs/spec/2026-10-16-ollama-file-parts.md`. Stack: aigateway (sdlc-python, TDD).

1. **RED** `tests/unit/test_ollama_content_parts.py`:
   - `check_messages(allow_files=False)` refuses a `file` part (`part_type: file`, `reason: files_unsupported`);
     default still accepts it;
   - Ollama `prepare_chat_body`: PDF part → 422; remote image URL → 422 `remote_url`;
     data-URI image in user, system and assistant messages passes; text-only body unchanged;
   - through the real route: PDF to `ollama/...` → 422 and dispatch never called.
2. **GREEN** add the flag in `core/content_parts.py`; call the gate in the Ollama plugin.
3. **Gates** `run_gates.py aigateway`; live re-run on the local `qwen2.5vl:3b`.
4. **PR** after the bug leaf under `OME-1529` is confirmed and filed.
