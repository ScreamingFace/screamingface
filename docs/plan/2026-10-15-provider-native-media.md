# Plan — provider native media (`OME-1541`)

Spec: `docs/spec/2026-10-15-provider-native-media.md`. Stack: aigateway (sdlc-python, TDD).

1. **Translator** — `core/content_parts.py` + `tests/unit/test_content_parts.py`.
   RED: text/str parts, data-URI image, bare-string image url, https image, PDF file part,
   unsupported type, malformed data URI (no `;base64`, empty payload), order preserved.
2. **Error type** — `UnsupportedContentPart` (422, typed detail) in `core/content_parts.py`.
   RED: status, detail shape; confirm the dispatch path neither retries nor marks the credential.
3. **Gemini adapter** — use the translator in `_message_to_content`.
   RED: text-only bodies byte-identical (golden from current code), interleaved text/image order,
   image-only turn kept, PDF → `inlineData application/pdf`, remote url → 422, system/tool media → 422.
4. **Antigravity adapter** — same tests, same change (shared helper from step 3 where the two
   copies already match; no new cross-plugin import — the helper lives in core).
5. **Codex adapter** — `_build_payload`.
   RED: text-only payload byte-identical, `input_text`/`input_image`/`input_file` order,
   https image passed as url, media on assistant/system → 422.
6. **Gates** — `run_gates.py aigateway` green.
7. **PR** — confirm, file `OME-1541` leaf work at PR-open (already exists: link it), `Refs: OME-1541`.
8. **After merge + staging deploy** — external 12-call run with a CF Access cookie file; post the
   table to `OME-1598`; scope `OME-1546` from the usage results.
