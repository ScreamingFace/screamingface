# Plan — image and file token accounting, gateway half (`OME-1546`)

Spec: `docs/spec/2026-10-20-image-token-accounting.md`. Stack: aigateway (sdlc-python, TDD).

1. **Parser** — `core/usage_modalities.py::image_and_file_tokens_from_gemini` +
   `tests/unit/test_usage_modalities.py`. RED: recorded TEXT+IMAGE+DOCUMENT metadata, text-only
   → 0, absent/empty/not-a-list → None, missing tokenCount → 0, malformed entry / negative / bool
   / non-string modality → None, overflow → None.
2. **Codex** — `_usage_from_response` writes the explicit `null`. RED in `tests/unit/codex/`.
3. **Gemini adapter** — `_usage_from_response` adds `prompt_tokens_details`. RED in
   `tests/unit/gemini/`: breakdown present → value through `ModelResponse.model_dump()`; absent →
   null; totals unchanged.
4. **Antigravity adapter** — same, `tests/unit/antigravity/`.
5. ~~Route stamp~~ — tried, reverted: it breaks three prior tests that pin the pass-through body
   (see spec). Left as an owner question on the ticket.
6. **Gates** — `uv run .claude/scripts/run_gates.py aigateway`.
7. **Live e2e** on 9132 (four providers × image/PDF), compare `prompt_tokens` with 2026-10-16.
8. **Codex cached-tokens bug** — live evidence captured (raw tap), filed as a separate `bug`
   (Triage, unassigned, no parent, Irina + Kevin tagged). Not fixed here.
9. **PR** — rename branch `OME-1546-…`, mirror in `docs/tasks/`, `Refs: OME-1546`, reviewer
   HupBaHa, engine follow-up recorded on the ticket.
