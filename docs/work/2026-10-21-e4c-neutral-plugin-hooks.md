---
ticket: OME-1703
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-21
finished:
---

# e4c-neutral-plugin-hooks — the surviving Profile-named plugin hooks get neutral names

## Intent

Stage E of `OME-1209` (epic `OME-1138`), landing E4c of E4 (plan §3 E4c, spec §9). After E4a and
E4b no runtime path reads or writes a Profile document, but four plugin hooks and the first
parameter of the strategy hooks still carry the Profile name. E4c renames them:
`allows_chatless_profile` → `allows_chatless_credential`, `profileless_auth_mode` →
`credentialless_auth_mode`, `invalidate_profile_session` → `invalidate_credential_session`,
`should_mark_profile_error_on_dispatch_status` →
`should_mark_credential_error_on_dispatch_status`, and the `profile_name` parameter of
`oauth_strategy_for`, `api_key_strategy_for` and `credential_strategy_for` → `credential_name`.
Core looks most of these hooks up duck-typed with a silent default, so a plugin that kept an old
name would silently lose its behaviour; a guard test pins that no plugin or base class defines an
old name. Behaviour is unchanged.

## Planned changes

- `core/plugin_base/_provider.py`: the four hooks and the three strategy-hook parameters.
- Plugins that override them: `anthropic_provider`, `antigravity_provider`, `codex_provider`,
  `gemini_provider`, `huggingface_provider`, `local_provider`, `ollama_provider`,
  `openai_provider`, `openrouter_provider` (`plugin.py` each).
- Core lookups: `core/provider_access/auth_mode.py` (the helper `profileless_auth_mode` becomes
  `credentialless_auth_mode`, re-exported from `core/provider_access/__init__.py`),
  `core/provider_access/targets.py`, `core/provider_access/profile_authorize.py`,
  `routes/auth.py`, `routes/chat_dispatch.py` (its private wrapper follows the hook name),
  `routes/model_parameters.py`.
- Comments and docstrings naming an old hook: `core/oauth_base.py`,
  `core/plugin_base/_contract.py`, `core/provider_access/types.py`.
- Out of scope: the strategy classes' own `profile_name` constructor argument and attribute,
  `credential_strategy_from`, and the `credential_service_for` helpers. They are not plugin hooks.

## Test plan

New test first, `tests/unit/core/test_neutral_plugin_hooks.py`:

- no class in the hierarchy of any `ProviderPluginBase` subclass under `aigateway.plugins` (the
  plugin, `ProviderPluginBase`, `ProviderPluginCore`) defines an old hook name; every plugin module
  is imported, so a plugin outside a `*_provider` package is checked too, and every plugin
  `load_plugins` registers must be in the checked set;
- `ProviderPluginBase` defines every neutral hook with the old defaults (no chatless credential,
  no credentialless auth mode, a no-op session invalidation, no credential error on dispatch);
- every `*_strategy_for` defined in that hierarchy takes `credential_name` as its first parameter
  and no `profile_name`;
- no module under `src/aigateway` names an old hook, so no duck-typed lookup still asks for one;
- added after review: each provider plugin overrides exactly the neutral hooks its row in a table
  lists, so a misspelled override fails; every literal hook name core looks up on a plugin
  (`getattr`/`hasattr`) is a member of `ProviderPluginBase` or one of six declared optional
  members, so a misspelled lookup fails.

Prior tests change only by name (plan §4 E4c: "rename-only"): fake plugins and direct hook calls
in the provider-access, no-auth and per-provider suites move to the neutral names with every
assertion kept. They are listed in the Outcome and go in the PR's approval manifest.

## Acceptance

- The guard test fails on `origin/main` and passes after the rename.
- Full suite green with only names changed; `run_gates.py aigateway` green.
- `git grep` finds no old hook name under `apps/aigateway` outside the guard test.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Source: `core/plugin_base/_provider.py`, `_contract.py`,
  `core/oauth_base.py`, `core/provider_access/{__init__,auth_mode,profile_authorize,targets,types}.py`,
  `routes/{auth,chat_dispatch,model_parameters}.py`, and `plugin.py` of `anthropic`, `antigravity`,
  `codex`, `gemini`, `huggingface`, `local`, `ollama`, `openai` and `openrouter` providers (20
  files). The hook docstrings now say "credential" where they said "profile"; the relocation note
  in `profile_authorize.py` describes the moved session-invalidation wrapper instead of naming it.
  New test: `tests/unit/core/test_neutral_plugin_hooks.py` (8 functions, 36 cases). It finds plugin
  classes by importing every module under `aigateway.plugins`, not through `load_plugins`, which
  registers only `*_provider` packages, and seeds the set only from `aigateway.plugins` so it does
  not depend on import order. After review, two stale comments next to renamed code were fixed:
  `routes/model_parameters.py` ("credentialless mode") and `core/oauth_base.py` (the dispatch
  module and hook location).
- **Prior tests (rename-only, every assertion kept):** reversing the four hook renames in each file
  reproduces `origin/main` byte for byte. `tests/unit/core/provider_access/`: `provider_access_fake.py`,
  `provider_access_harness.py`, `test_no_auth_provider_access.py`,
  `test_provider_access_authorize_contract.py`, `test_provider_access_helpers.py`,
  `test_provider_access_port_shape.py`, `test_provider_access_resolve_contract.py`; and
  `tests/unit/core/test_no_auth_mode.py`, `tests/unit/gemini/test_gemini_provider.py`,
  `tests/unit/gemini/test_gemini_routes.py`, `tests/unit/huggingface/test_huggingface_dispatch.py`,
  `tests/unit/huggingface/test_huggingface_provider.py`, `tests/unit/ollama/test_ollama_provider.py`,
  `tests/unit/openai/test_openai_provider.py`, `tests/unit/openrouter/test_openrouter_dispatch.py`
  (15 files). Fake plugins keep their `profile_name` strategy parameter: they are not production
  plugins, and core passes that argument by position.
- **Commits:** `1be3988e9` refactor(aigateway)!: give the plugin hooks credential names; a docs
  commit carries the `docs/tasks` mirror and the approval manifest.
- **Gates:** RED: the guard test failed 19 of 25 cases on `origin/main` (old names defined, neutral
  names missing). Probe: a temporary plugin package outside `*_provider` with a `profile_name`
  strategy parameter and an old hook name failed three guard cases; the probe was removed.
  Mutations (each restored, file diff empty after): a misspelled override in the Local plugin, a
  misspelled lookup in `routes/auth.py`, and an old name kept in the Gemini plugin each fail the
  guard; before the review fixes the first two passed the whole suite. GREEN:
  `run_gates.py aigateway --base origin/main` — ruff, format, pyright, no-enterprise guard and
  pytest with coverage all green (6151 tests collected). After the rebase onto `origin/main`
  (`dc695cfd2`), the full gate with `--base origin/main`, append-only included: all green, 6277
  tests collected; the 15 prior-test transitions are approved by
  `.claude/test-change-approvals/OME-1703.json`. PostgreSQL lane
  (`AIGW_TEST_PG=1 uv run pytest -m needs_postgres`): 60 passed, 5 failed, all five in
  `test_cache_snapshot_upload_postgres.py` at the `pg_dump` call — the local 15.13 client against
  the PostgreSQL 16 test container, the same local-only set as on E4b; E4c does not touch that
  module.
- **Review:** an independent read-only review found no blocker: no old name left in a call,
  lookup, keyword argument, patch target or current document; prior tests name-only; guard
  discovery stable between an isolated and a full run. It showed that a misspelled new name still
  failed silently (Local plugin: `/v1/model-parameters` would report `execution_access: missing`;
  `routes/auth.py`: a replaced credential's session would not be dropped). The override table and
  the lookup check above close both.
- **Deviations:** the guard goes past plan §4's minimum ("no plugin or base class defines an old
  hook name"): it also pins the override table and the core lookups, because a misspelling fails
  as silently as a missed rename. Not renamed, because they are not plugin hooks: the strategy
  classes' `profile_name` argument and attribute, `credential_strategy_from`, and the
  `credential_service_for` helpers.
