# Plan — harden file intake

Spec: `docs/spec/2026-10-20-harden-file-intake.md`. Stack: aigateway (sdlc-python, TDD).
Ledger: `docs/work/2026-10-20-harden-file-intake.md`.

1. **Body cap.** RED `tests/unit/test_body_cap_middleware.py` (declared-over, chunked-over,
   lying-length, exactly-at-limit, message names bytes+MiB, swallowed-exception override,
   per-path limit, non-http scope passthrough) + `test_body_cap_settings.py` (default, env, >0)
   + a route test through `create_app`. GREEN `middleware/body_cap.py`, `config.py`, `main.py`.
2. **data:-only guard.** RED `tests/unit/core/test_media_intake.py` (table of parts × outcome)
   + `tests/unit/test_chat_remote_media_route.py` (every LiteLLM-backed provider → 422 before
   cache lookup and dispatch; Codex https passes the guard). GREEN `core/media_intake.py`,
   `_provider.py` flag, Codex opt-in, `routes/chat.py` call.
3. **Anthropic system media.** RED `tests/unit/anthropic/test_anthropic_system_media.py`
   (message + top-level system → 422, text unchanged, projection bypass). GREEN `plugin.py`.
4. **Cache invariant.** RED-able test: a provider with `forwards_remote_image_urls` has no
   global cache projection.
5. Gates: `uv run .claude/scripts/run_gates.py aigateway`.
6. Live e2e on :9131 (copied DB), logging HTTP server for zero-hit proof.
7. Ledger outcome, commit, file mirror, rename branch `OME-1542-harden-file-intake`, PR
   `Refs: OME-1542`, reviewer HupBaHa, watch CI.
