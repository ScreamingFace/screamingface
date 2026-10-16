---
ticket: OME-1541
stack: aigateway
status: in_progress
started: 2026-10-15
finished:
---

# provider-native-media — send images and PDFs to Gemini, Antigravity and Codex natively

## Intent

Stop the silent image drop in the three custom adapters: translate OpenAI image/file parts into
each provider's native part, or return a typed 422. Deployed to staging, it also answers spike
`OME-1598` from outside. Spec: `docs/spec/2026-10-15-provider-native-media.md`.

## Planned changes

- `apps/aigateway/src/aigateway/core/content_parts.py` (new)
- `apps/aigateway/src/aigateway/plugins/gemini_provider/message_adapter.py`
- `apps/aigateway/src/aigateway/plugins/antigravity_provider/message_adapter.py`
- `apps/aigateway/src/aigateway/plugins/codex_provider/chat_handler.py`
- tests under `apps/aigateway/tests/unit/` (new files only)

## Test plan

See `docs/plan/2026-10-15-provider-native-media.md` steps 1–5.

## Acceptance

- No adapter path drops a non-text part: translated or 422 with provider + part type.
- Text-only requests byte-identical to today on all three adapters.
- `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the gate in each plugin's `prepare_chat_body`
  (`plugins/{gemini,antigravity,codex}_provider/plugin.py`); tests
  `tests/unit/test_content_parts.py`, `tests/unit/test_native_media_adapters.py`.
- **Commits:** see the branch (`feat(aigateway): send images and PDFs natively to Gemini, Antigravity and Codex`).
- **Gates:** `run_gates.py aigateway` → ALL GATES GREEN (ruff, pyright, no-enterprise, pytest ≥80% cov).
- **Deviations:**
  - The 422 is raised in `prepare_chat_body` (route, pre-dispatch) as well as in the adapters,
    because LiteLLM remaps exceptions raised inside a custom handler.
  - `UnsupportedContentPart.info` carries a typed copy of the detail (`HTTPException.detail` is `str`).
  - Cache: the three providers use the default `CacheBypass`, so no drop-era answer can be
    served from the exact-request cache.
  - PR #1431 review: image `detail` carried through (Codex `input_image.detail` is Required,
    default `auto`); `image_url` must be `image/*` and `file` must be `application/pdf`; untyped
    non-text mappings are refused (`part_type: untyped`). Two PR-local tests changed with owner
    approval (`{}` no longer skippable; Codex payload pinned without `detail`); gates run with
    `--skip-append-only` for that change only.
  - PR #1431 follow-up review: a non-string `image_url.detail` (list/dict, unhashable) raised
    TypeError → 500; now a typed 422. Tests appended only.
  - Route-level coverage: `tests/unit/test_native_media_route.py` drives `/v1/chat/completions`
    (Codex) and pins the typed 422 reaching the HTTP caller with no dispatch; mutation-checked
    (gate disabled → 4 of 5 fail).
  - Not yet verified live: the external 12-call run after the staging deploy answers `OME-1598`.
