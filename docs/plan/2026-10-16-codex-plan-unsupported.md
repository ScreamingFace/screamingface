# Plan — Codex model refusal + live Codex model list (`OME-1634`)

Spec: `docs/spec/2026-10-16-codex-plan-unsupported.md`. Stack: aigateway (sdlc-python, TDD).

1. **Rename** `codex_plan_unsupported` → `codex_model_unsupported` in
   `tests/unit/test_codex_plan_unsupported.py` (this PR's own test; rename + new message only) and
   `plugin.py`.
2. **RED** `tests/unit/test_httpx_discovery_headers.py`: `HttpxDiscoveryClient(headers=...)` sends them
   (MockTransport); default sends none beyond identity encoding.
3. **RED** `tests/unit/codex/test_codex_live_models.py`:
   - parser: only `visibility == "list"` slugs, order-stable dedupe; malformed envelope/row →
     `malformed_json`; none listed → `model_catalog_empty`; over cap → `model_catalog_too_large`;
   - directory: no account id → `None`, no dial; dial carries Bearer / ChatGPT-Account-Id /
     originator to the fixed URL; cached per account within TTL; failure → `None`, last good kept
     (stale);
   - ~~shared `latest()` listing via `model_discovery_source()`~~ — **superseded 2026-10-17**
     (security review): no `model_discovery_source`; the per-account directory serves only that
     account's refusal, `/v1/models` lists the static seeds (regression: an account refresh never
     changes the shared listing);
   - refusal: 403 carries `available_models` when the directory knows the account's list, omits it
     when not; a directory failure never changes the 403.
4. **GREEN** core `parameter_discovery.py` (`headers`), `codex_provider/live_models.py` (new),
   `plugin.py` wiring.
5. **Gates** `run_gates.py aigateway`; live e2e on port 9121 with a DB copy.
6. **PR #1441** retitle + body (`Refs: OME-1634`). Static-slug swap to the four live slugs plus the
   two pinning `main` tests: **owner-approved 2026-10-17** (Sergey, working session).
7. **Review 2026-10-20 (HupBaHa):** RED `tests/unit/codex/test_codex_refusal_provenance.py` — the
   marker in `error.message` (plain or detail-shaped) is not re-typed and reads no list; top-level
   `detail` wins over an unrelated `error.message`; the exception path agrees; plan claim bounded.
   GREEN: `chat_handler` reads `detail` first and relays it as `{"detail": ...}`, withholds a mimic;
   `plugin._is_model_refusal` classifies only that shape; `plan_type_from_token` bounded.
