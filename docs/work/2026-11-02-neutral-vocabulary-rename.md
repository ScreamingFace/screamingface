---
ticket: OME-1812
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-02
finished:
---

# neutral-vocabulary-rename — OME-1138 close-out L5: neutral credential vocabulary, rename-only

## Intent

Leaf L5 of the OME-1138 close-out (spec `docs/spec/2026-10-29-ome-1138-closeout.md` §4.5, plan
section "L5"; both accepted by the owner 2026-10-29). Stage E retired the Profile, but the runtime
still names a credential's address `profile_name`, threads the always-`default` selector name
through chat as `profile_name`, logs it as `profile=`, keeps the authorize module under
`profile_authorize`, and tells a user that "the profile" must be reconnected. This unit renames
those to the Connection vocabulary with no logic change, drops the constant thread and the log
field (Q6), and words the two model-admission refusals in Connection terms (RT-05). L4b merged
first, so this branches from `origin/main`.

## Planned changes

Gateway src (`apps/aigateway/src/aigateway/`):

- Strategies: `profile_name` becomes `credential_name` in `core/plugin_base/_resolvers.py`
  (`credential_strategy_from`), `core/oauth_base.py` (`BaseOAuthStrategy`),
  `core/api_key_strategy.py` (`ApiKeyStrategy`), `plugins/remote_endpoint/credential.py`
  (`OriginBoundApiKeyStrategy`), each plugin's `auth.py` (`credential_service_for` and the strategy
  classes), the plugins' `plugin.py` call sites and `_credential_service_for` helpers, and
  `routes/oauth_connections.py`.
- Chat: `routes/chat.py` stops threading `selector.name` as `profile_name`; `routes/chat_dispatch.py`
  drops the parameter from `_safe_dispatch_failure_response`, `log_dispatch_failure` and
  `_record_dispatch_success`, and the `profile=%s` field from both log lines (Q6).
- Module: `core/provider_access/profile_authorize.py` becomes `connection_authorize.py`; its six
  importers follow.
- `PendingAuthEntry.profile_name` (`core/pending_auth.py`) becomes `fallback_label`;
  `routes/auth.py` and the entry's constructors follow.
- Messages (RT-05): `routes/model_admission.py` says "connection" in the reauth and pending
  refusals, and drops the selector name, which is always `default` since L4a; the `ApiKeyStrategy`
  help text says "connection". The codes `profile_not_found` and `profile_pending_auth` stay (R3).
- Migrations are history and keep their column names.

Gateway tests (`apps/aigateway/tests/`): new tests below, plus the prior tests that name a renamed
symbol (spec §6 L5 row), each pinned in the test-change manifest at PR-open.

No schema or model change, so no migration (S1 not triggered).

## Test plan

RED first:

- `unit/core/test_neutral_credential_vocabulary.py`: no `profile_name` identifier, attribute,
  parameter or keyword in gateway src outside `migrations/`; no `profile_authorize` module, and
  `connection_authorize` exists. RED on the current tree.
- `unit/test_dispatch_failure_records_handler_error.py`: the terminal record carries no `profile=`
  field and `log_dispatch_failure` takes no selector name. RED (the call without it raises).
- `unit/openrouter/test_model_admission_route.py`: the reauth and pending refusals read exactly
  "the openrouter connection must be reconnected …" and "… is still connecting …", with no
  "profile". RED on the current wording.
- GREEN: the full `aigateway` suite (`run_gates.py aigateway --base origin/main`), then the
  `needs_postgres` lane.

## Acceptance

- No `profile_name` identifier in gateway src outside `migrations/`; no `profile_authorize`
  module; no `profile=` log field.
- The two model-admission refusals and the `ApiKeyStrategy` help text say "connection"; the wire
  codes are unchanged.
- The diff carries no expression change beyond the dropped constant thread and the message text.
- `run_gates.py aigateway --base origin/main` green; the PG lane green; every changed prior test
  is in `.claude/test-change-approvals/OME-N.json`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files (47 under `apps/aigateway`, plus this ledger, the mirror and the manifest):**
  - src (28): the planned sites. `profile_authorize.py` moved to `connection_authorize.py` with
    its six importers; the strategies, the plugins' `auth.py` and `plugin.py`, `_resolvers.py`
    and `remote_endpoint/credential.py` say `credential_name`; `pending_auth.py`, `routes/auth.py`
    and `routes/oauth_connections.py` say `fallback_label`; `routes/chat.py` and
    `routes/chat_dispatch.py` drop the constant thread and the `profile=` field;
    `routes/model_admission.py` and `core/api_key_strategy.py` carry the new wording. Docstrings
    in `api_key_strategy.py` and `oauth_base.py` say "connection" where they said "profile".
  - tests (19): the three RED files, one of which also drops the retired argument from two prior
    calls, and 16 prior files that name a renamed symbol (spec §6 L5 row). Each changed line is
    an import, a module path, a keyword, an attribute read or a dropped argument; no expected
    value changes. All 19 are pinned in the manifest.
- **Commits:** `refactor(aigateway): name credentials and connections in the runtime vocabulary`.
- **RED seen:** the AST guard listed every `profile_name` site in src; `find_spec` found
  `profile_authorize` and no `connection_authorize`; `log_dispatch_failure` raised `TypeError`
  without the selector name; both admission refusals read "profile 'default'".
- **Gates:** `run_gates.py aigateway --base origin/main` (base `0a4aa1bef`, 2026-11-02): ruff,
  format, pyright, the no-enterprise check and pytest with coverage passed. The append-only check
  against `origin/main` then passed with `.claude/test-change-approvals/OME-1812.json` pinning all
  19 changed test files. `needs_postgres` lane: 67 passed.
- **Deviations:**
  - The spec scopes the message change to the two admission refusals and the `ApiKeyStrategy`
    help text, so the plugins' own errors still say "profile" ("No tokens for <provider>
    profile …", "Refresh token rejected for profile …"), as does the `x-aigw-gemini-profile`
    header, which is wire. Two of those literals were split to fit the line limit, text
    unchanged.
  - The admission refusals no longer name the selector: it is always `default` since L4a.
