---
ticket: OME-1403
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-09-29
finished: 2026-09-29
---

# engine-cors-studio — Engine answers CORS for the Studio frontend

## Intent

The Studio app (`apps/screamingface-studio`, Next.js inside Tauri 2) will call the Engine's
REST surface from its webview instead of mock data (epic OME-1308, E18 · A local app). A
browser/webview blocks those cross-origin calls unless the Engine sends CORS headers. Add a
`CORSMiddleware` whose allowed origins are Studio's only, configurable through `Settings`.

Spec: `docs/spec/2026-09-29-engine-cors-studio.md` · Plan: `docs/plan/2026-09-29-engine-cors-studio.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/config.py` — `cors_allowed_origins` field.
- `apps/screamingface-engine/src/screamingface_engine/cors.py` — new; `install_cors(app, origins)`.
- `apps/screamingface-engine/src/screamingface_engine/app.py` — call `install_cors` in `create_app`.
- `apps/screamingface-engine/tests/unit/test_cors.py` — new.
- `apps/screamingface-engine/README.md` — document `URL4_CLOUD_CORS_ALLOWED_ORIGINS`.

## Test plan

- Default `Settings().cors_allowed_origins` is exactly Studio's four origins.
- Preflight (`OPTIONS` + `Access-Control-Request-Method`) from each default origin → 200 with
  `access-control-allow-origin` echoing that origin; `Authorization` allowed.
- Simple `GET /healthz` from an allowed origin carries `access-control-allow-origin`.
- Preflight from a foreign origin (`https://evil.example`) → no `access-control-allow-origin`.
- No `access-control-allow-credentials` header (credentials off).
- `URL4_CLOUD_CORS_ALLOWED_ORIGINS='["https://x.example"]'` replaces the defaults.
- Empty list → no CORS headers for any origin (fail closed).

## Acceptance

- Studio dev (`http://localhost:3000`) and packaged Tauri origins can call Engine REST.
- Any other origin gets no CORS grant; the list is overridable by env.
- All `screamingface-engine` gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `config.py` (`STUDIO_CORS_ORIGINS` + `cors_allowed_origins`),
  new `cors.py` (`install_cors`), `app.py` (new `_install_middleware` holding Metrics + CORS),
  new `tests/unit/test_cors.py` (11 tests), README `## CORS` section.
- **Commits:** see branch history — `feat(screamingface-engine): grant CORS to the Studio frontend's origins`
- **Gates:** ruff check ✓ · ruff format ✓ · pyright 0 errors ✓ · check_layering ✓ ·
  pytest 4094 passed / 1 failed, coverage 93.67% (≥80). The one failure,
  `test_chart_render_tracing.py::test_the_template_refuses_too_when_schema_validation_is_skipped`,
  is environmental: local helm v3.14.2 lacks `--skip-schema-validation` (helm ≥3.16); CI pins
  helm via `azure/setup-helm`. Unrelated to this change.
- **Deviations:** (1) `_install_middleware` helper added to `app.py` because one more statement
  in `create_app` tripped ruff PLR0915. (2) Added a test that a handled 404 carries the grant, so
  Studio can read Engine problem bodies. Unhandled-exception 500s come from Starlette's
  outermost `ServerErrorMiddleware` and do not carry CORS headers — acceptable, noted in code.
