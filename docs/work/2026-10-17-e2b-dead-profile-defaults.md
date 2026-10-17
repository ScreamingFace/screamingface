---
ticket: OME-1645
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-17
finished: 2026-10-17
---

# e2b-dead-profile-defaults — delete the dead chat shims and the saved-defaults pipeline

## Intent

Landing E2b of Stage E (`OME-1209`, spec `docs/spec/2026-10-14-OME-1209-retire-legacy-profiles.md`
§3, plan §3 E2b). Stage C (`OME-1323`) stopped the chat route from reading or merging stored
Profile defaults, and A2 (`OME-1207`) moved every route off the `chat_credentials` shim. The code
that served both is now reachable only from its own tests. This unit deletes it, so E4 does not
carry a second, dead credential vocabulary. The stored `ProfileDefaults` on Profile documents stay
(the documents are E5's); only the pipeline that read and merged them goes.

## Planned changes

Under `apps/aigateway/src/aigateway/`:

- Delete `routes/chat_credentials.py` and `routes/chat_profile_defaults.py` (no production
  importer).
- Delete `core/provider_access/defaults.py` (`apply_defaults`) and
  `core/provider_access/profile_defaults.py` (`read_defaults`).
- `core/provider_access/types.py`: drop `RequestDefaults` and `CredentialTarget.defaults`.
- `core/provider_access/ports.py`: drop `ProviderAccess.defaults_for`.
- `core/provider_access/profile_backed.py`, `connection_backed.py`: drop `defaults_for` and the
  `defaults=` argument of every target builder; drop `legacy_target_parts` and
  `target_from_legacy` if the shim was their only caller.
- `core/provider_access/__init__.py`: drop the removed exports.
- `core/plugin_base/_provider.py`, `plugins/anthropic_provider/plugin.py`: drop the
  `should_apply_profile_default` hook and its override.
- No live re-export needs a new home: every route already calls the port directly.

## Test plan

- RED: a new test that the shim modules and the defaults modules no longer import, that the port
  and target carry no defaults surface, and that no plugin defines `should_apply_profile_default`.
- Proof the code is dead: the Stage C suites (`test_chat_saved_defaults_are_not_merged.py`,
  `test_chat_global_cache_effective_request.py`, `test_chat_global_cache_key_parity.py`) and the
  chat characterisation suites stay green unchanged after the deletion.
- Prior tests that only pinned a deleted declaration retire; tests that import a deleted name
  for setup change that line only. Both lists, with a reason per file, go into
  `.claude/test-change-approvals/OME-<E2b>.json` for owner approval before commit.

## Acceptance

- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` green.
- `git grep -nE 'RequestDefaults|defaults_for|apply_defaults|should_apply_profile_default|chat_credentials|chat_profile_defaults' -- apps/aigateway/src`
  finds nothing outside comments that record history.
- OpenAPI byte-identical to the base (no route changes).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Deleted the four modules; edited `types.py`, `ports.py`,
  `profile_backed.py`, `connection_backed.py` (docstring), `connection_authority.py`,
  `__init__.py`, `plugin_base/_provider.py`, `anthropic_provider/plugin.py`. New test
  `tests/unit/core/provider_access/test_saved_defaults_pipeline_removed.py`. Test fallout in 13
  files, owner-approved in `.claude/test-change-approvals/OME-1645.json`. Also closes the OME-1640
  mirror and ledger (`status: done`).
- **Commits:** one squash-ready commit on `OME-1645-delete-dead-chat-shims-and-saved-defaults`.
- **Gates:** `run_gates.py aigateway --base origin/main` all green (append-only with 11 approved
  transitions, ruff, format, pyright, no-enterprise, pytest with coverage >= 80). RED: 11 failed
  before the deletion. Full unit suite 6146 passed, 2 skipped. OpenAPI byte-identical to
  `origin/main`. The Stage C suites stayed green unchanged.
- **Deviations:** `test_chat_profile_default_provenance.py` is kept as a docstring-only module
  instead of deleted: the append-only gate rejects any whole-file deletion and a manifest cannot
  approve one. `legacy_target_parts` and `target_from_legacy` had no caller but the shim and went
  with it. The A1 shim suite keeps its wiring tests; the substitution test now calls the port's
  `resolve` directly.
