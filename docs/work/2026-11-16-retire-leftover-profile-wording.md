---
ticket: OME-1940   # SDK leaf: OME-1941; both under OME-1138
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-16
finished:
---

# retire-leftover-profile-wording — retire the Profile wording the OME-1138 close-out left

## Intent

The OME-1138 close review found Profile wording after the epic closed: the provider plugins'
credential errors and the Gemini 401 still say "profile" (and send the caller to the retired
desktop app), about 25 gateway comments describe Profiles as present, eight gateway test doubles
keep a `mutate` that nothing calls, and an SDK fixture still sends the scope `account_profile`.
Spec: `docs/spec/2026-11-16-ome-1138-leftover-profile-wording.md`; plan:
`docs/plan/2026-11-16-ome-1138-leftover-profile-wording.md`.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/{anthropic,antigravity,codex,gemini}_provider/auth.py`:
  the two credential error messages.
- `apps/aigateway/src/aigateway/plugins/gemini_provider/chat_handler.py`: the 401 message and one
  docstring.
- The comments listed in spec §2.2.
- The eight test doubles in spec §2.3 lose `mutate`.
- `packages/screamingface/tests/test_hosted_byom_preflight.py`: the fixture scope.
- New tests pinning the messages (plan step 2).
- At PR-open: `.claude/test-change-approvals/OME-<leaf 1>.json` and two `docs/tasks` mirrors.

## Test plan

- RED: per OAuth plugin, the missing-tokens and refresh-rejected messages; the Gemini 401 without
  a credential or an environment key. Each asserts the new text and the absence of "profile" and
  "Electron".
- Then the full gateway and SDK suites through `run_gates.py`.

## Acceptance

- Spec §4.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - Messages: `plugins/{anthropic,antigravity,codex,gemini}_provider/auth.py` and
    `plugins/gemini_provider/chat_handler.py` under `apps/aigateway/src/aigateway/`.
  - Comments (spec §2.2): `core/auth/cloudflare_identity.py`, `core/auth_types.py`,
    `core/credential_strategy_cache.py`, `core/plugin_base/_ports.py`,
    `core/plugin_base/_provider.py`, `core/request_hardening.py`, `core/secrets/local.py`,
    `core/request_cache/{global_eligibility,global_keys,global_plan,tavily_retrieval}.py`,
    `plugins/openai_provider/{runtime_guard,settings}.py`, `routes/chat_cache_stage.py`,
    `plugins/codex_provider/{plugin,live_models}.py`, `plugins/huggingface_provider/plugin.py`,
    `plugins/openrouter_provider/plugin.py`, `routes/chat_dispatch.py`,
    `routes/model_admission.py`.
  - New test: `apps/aigateway/tests/unit/test_plugin_credential_wording.py` (9 cases).
  - Test doubles without `mutate` (spec §2.3): the eight files listed there.
  - SDK fixture: `packages/screamingface/tests/test_hosted_byom_preflight.py`.
  - Docs: this ledger, the spec and the plan.
- **Commits:** `2e0aa6bfa` `fix(aigateway): name the credential, not a retired Profile, in
  provider errors`; then the docs, the two mirrors and
  `.claude/test-change-approvals/OME-1940.json` (nine prior test files pinned byte-exact).
- **Gates:** first run on `origin/main` `66962a178`.
  - RED: the 9 new cases failed on the old wording; GREEN: 9 passed.
  - `aigateway`: ruff check, ruff format, pyright (0 errors), `check_no_enterprise`, pytest
    7910 passed / 119 skipped, coverage 94.16% (floor 80%).
  - `screamingface`: ruff check, ruff format, pyright (0 errors), pytest 7473 passed /
    38 skipped, coverage 97.03% (floor 95%), `credit_refresh` node test, notebooks check,
    `uv build`, distribution check.
  - `run_gates.py` stopped at the append-only check on the nine changed test files until
    `.claude/test-change-approvals/OME-1940.json` existed (plan step 7). With it, the full
    runner passed for both stacks on `a23e84311`, the nine files approved byte-exact.
- **Deviations:**
  - The new tests are one parametrized module, not one addition per plugin test file (plan
    step 2). The four plugins share the contract, so one module states it once; the per-plugin
    files keep their own fixtures unchanged.
  - The Gemini handler's local `profile_key` is now `connection_key`; the spec listed only the
    message and the docstring.
  - `ruff format` joined the Codex and Gemini missing-tokens literals onto one line each.
  - `core/secrets/local.py` keeps "profile-id lists" as history ("nor did the retired
    profile-id lists"), because the comment explains why the envelope pattern cannot match a
    value stored before the purge.
  - Deleting `mutate` left `Callable` unused in the two `remote_endpoint` test files; the import
    is removed. In `remote_endpoint/test_plugin.py` the deleted `mutate` raised to prove the
    strategy never mutates; the store port no longer has `mutate`, so a stray call would still
    fail that test.
  - The branch was fast-forwarded from `c1bca6a86` to `origin/main` `66962a178` before the
    first gate run, and the commit was rebased onto `a23e84311` before PR-open. Neither range
    touches the gateway, the SDK or the gate scripts; the gates are rerun on the new base.
