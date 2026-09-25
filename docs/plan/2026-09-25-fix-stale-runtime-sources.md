---
title: A dev checkout's local stack always runs the live url4 and apps
ticket: unfiled
status: approved
date: 2026-09-25
spec: ../spec/2026-09-25-fix-stale-runtime-sources.md
---

# A dev checkout's local stack always runs the live url4 and apps

1. Add `hatchling` to the `dev` dependency group and relock.
2. Add failing tests:
   - `tests/test_runtime_build_hook.py`: a real `hatchling.build.build_editable` of this
     package produces a wheel with no `url4/`, `aigateway/`, `scoreboard/`,
     `screamingface_engine/` entries and a `.pth` listing exactly the four live source
     directories (all of which exist). A real `build_wheel` still vendors `url4/__init__.py`.
   - `tests/test_runtime_source.py` (append only): a module file inside the checkout root
     but outside the source directories (a `.venv` under the root) is rejected, and the
     message carries the reinstall command.
3. Implement the editable branch in `scripts/runtime_build_hook.py`: write the `.pth` to a
   temp dir, set `force_include_editable`, and clean up in `finalize`.
4. Tighten `verify_live_modules` in `_runtime/source.py` to the source directories, and
   add the reinstall hint.
5. Add `[tool.uv] cache-keys` covering `pyproject.toml` and the hook.
6. Verify by hand: `uv sync` in the worktree venv. Check that `site-packages/url4` is gone,
   that `url4.__file__` resolves to `packages/url4/src`, and that `require_runtime_extra()`
   passes.
7. Run the screamingface stack gates.
