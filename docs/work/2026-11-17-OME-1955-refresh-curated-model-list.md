---
ticket: OME-1955
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-11-17
finished: 2026-11-17
---

# OME-1955 — refresh the curated model list

## Intent

The curated model list is three months behind OpenRouter: nine of the ten most used models are
not in `sf.models.list()`. Add the new models of the large labs, show the newest models first,
and let the user search with more than one word. Spec:
`docs/spec/2026-11-17-OME-1955-refresh-curated-model-list.md`.

## Planned changes

- Plan: `docs/plan/2026-11-17-OME-1955-refresh-curated-model-list.md` (draft; the owner must approve it before code). This ledger is for PR A of the plan.
- Expected files for unit 1 (from the spec, §5.1):
  - `apps/aigateway/src/aigateway/plugins/openrouter_provider/settings.py`
  - `apps/aigateway/tests/unit/openrouter/test_openrouter_settings.py`
  - `apps/screamingface-engine/src/screamingface_engine/world/models/seeds/openrouter.py`
  - `apps/screamingface-engine/tests/unit/test_model_seeds.py`

## Test plan

- The tests of the spec, §9, written first.

## Acceptance

- The spec, §12.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** Changed: apps/aigateway/src/aigateway/plugins/openrouter_provider/settings.py (+51); apps/aigateway/tests/unit/openrouter/test_openrouter_settings.py (+50); apps/screamingface-engine/src/screamingface_engine/world/models/seeds/openrouter.py (+49); apps/screamingface-engine/tests/unit/test_model_seeds.py (+9 -2). New: apps/aigateway/scripts/check_openrouter_seeds.py; apps/aigateway/tests/unit/openrouter/test_check_openrouter_seeds.py; docs/spec/2026-11-17-OME-1955-refresh-curated-model-list.md; docs/plan/2026-11-17-OME-1955-refresh-curated-model-list.md; docs/tasks/2026-11-17-OME-1955-refresh-curated-model-list.md; docs/work/2026-11-17-OME-1955-refresh-curated-model-list.md.
- **Commits:** `c91b683d0` chore(aigateway): add a command that compares the OpenRouter seeds with the catalogue; `d20b65b09` feat(aigateway): add 49 OpenRouter models to the curated list. The docs commit follows them.
- **Gates:** Final run on 2026-11-17, one stack at a time, after the design review fixes:
  - `uv run .claude/scripts/run_gates.py aigateway --skip-append-only`: ALL GATES GREEN (ruff check, ruff format, pyright, check_no_enterprise, pytest with coverage).
  - `uv run .claude/scripts/run_gates.py screamingface-engine --skip-append-only`: ALL GATES GREEN (ruff check, ruff format, pyright, check_layering, pytest with coverage).
  - The append-only check, run without the skip flag, names only the two approved files: `apps/aigateway/tests/unit/openrouter/test_openrouter_settings.py` and `apps/screamingface-engine/tests/unit/test_model_seeds.py`. It stays red until the manifest of plan step A3 exists.
  - `uv run python scripts/check_openrouter_seeds.py` (network, 2026-11-17): 4 dead seeds (`qwen/qwen3.8-max`, `anthropic/claude-opus-5-fast`, `nex-agi/nex-n2-mini`, `liquid/lfm-2.5-2.6b:free`), 0 new models. Thus each of the 49 added ids is in the live catalogue.
- **Deviations:**
  - (a) Plan step A3: the owner approved the two test edits on 2026-11-17; the manifest is `.claude/test-change-approvals/OME-1955.json`. The label of `OME-1955` is now `aigateway`, and PR B and PR C are its sub-issues `OME-1956` and `OME-1957` (owner decision 2026-11-17).
  - (b) A first gate run was red on `tests/unit/auth/test_login.py::test_unknown_user_timing_close_to_wrong_password`. This is a timing test in a file that this change does not touch. It failed while three test suites ran at the same time on this machine, and it passed in the final run with one suite at a time.
  - (c) Design review (Opus), verdict ACCEPT-WITH-FIXES. Fixes applied: the script stops if the catalogue answer is paged (new test); `CATALOG_URL` uses `MODELS_URL` of `discovery.py`; the `~` clause is removed because the author test already excludes an alias; `_iso_date` has no `try`; the test that only repeated the 14 author names is removed; one assertion of the `main` test is stricter; the comment of the new Engine test uses `WHY`. Not applied: a warning when `AIGW_OPENROUTER_DEFAULT_MODELS` is set (the plan names `OpenRouterPluginSettings().default_models` as the source).
  - (d) The test helper `_row` in `test_check_openrouter_seeds.py` annotates `outputs` as `Sequence[str]`, because pyright rejects `list(outputs)` on `object`.
