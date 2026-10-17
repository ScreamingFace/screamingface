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
     (stale); `latest()` follows the most recent refresh and expires after the stale window;
   - plugin port: `model_discovery_source()` declared; `discover_live_models` → `codex/<slug>` rows
     from `latest()`, `DiscoveryError("no_snapshot")` when none;
   - refusal: 403 carries `available_models` when the directory knows the account's list, omits it
     when not; a directory failure never changes the 403.
4. **GREEN** core `parameter_discovery.py` (`headers`), `codex_provider/live_models.py` (new),
   `plugin.py` wiring.
5. **Gates** `run_gates.py aigateway`; live e2e on port 9121 with a DB copy.
6. **PR #1441** retitle + body (`Refs: OME-1634`); static-slug swap reported as blocked on the
   append-only test conflict.
