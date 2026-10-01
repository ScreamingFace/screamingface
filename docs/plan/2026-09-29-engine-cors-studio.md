---
status: approved 2026-09-29
spec: docs/spec/2026-09-29-engine-cors-studio.md
date: 2026-09-29
---

# Plan — Engine CORS for the Studio frontend

One unit, stack `screamingface-engine`, sdlc-python loop.

1. **RED** — `tests/unit/test_cors.py`: default origins; preflight grant per default origin
   (with `Authorization` in `Access-Control-Request-Headers`); simple GET grant; foreign
   origin refused; no credentials header; env override; empty list grants nothing.
2. **GREEN**
   - `config.py`: `cors_allowed_origins: list[str]` with the four Studio defaults
     (`default_factory`), anchored `FEATURE:`/`WHY:`.
   - `cors.py` (new, keeps `app.py` from growing): `install_cors(app, origins)` adding
     `CORSMiddleware(allow_origins=origins, allow_credentials=False, allow_methods=["*"],
     allow_headers=["*"])`.
   - `app.py`: call `install_cors(app, settings.cors_allowed_origins)` in `create_app`,
     after `MetricsMiddleware` so CORS is outermost and preflights are answered before
     routing.
3. **Docs** — README env table: `URL4_CLOUD_CORS_ALLOWED_ORIGINS`.
4. **Gates** — `uv run .claude/scripts/run_gates.py screamingface-engine`.
5. **PR-open** — confirm with owner; file leaf under OME-1308 (`app/screamingface-engine`,
   who-acts, `agentic`, assignee me), `docs/tasks/` mirror, rename branch to `OME-N-…`.
