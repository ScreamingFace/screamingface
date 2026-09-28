---
ticket: OME-1167
stack: aigateway
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1167 — Checking a model's parameter limits fails unless a provider is connected

## Intent

Reading a model's parameter contract is a datasheet lookup, not a credentialed action —
but today aigateway's `GET /v1/model-parameters` reuses the chat credential resolution,
which raises 404 `profile_not_found` when the account has no profile and no connection
for the provider. The Engine relays that verbatim and the SDK renders "profile is not
connected", so a keyless stack cannot preflight a params-carrying candidate. This unit
makes the contract answerable with no stored credential target, keeping dispatch and
connection flows byte-identical.

**Refusal origin (investigation result):** `apps/aigateway/src/aigateway/routes/chat_credentials.py`
`_credential_target_for_chat` — the `profile_not_found` raise when profile and active
connection are both absent and the plugin does not allow a chatless profile. The Engine
route (`apps/screamingface-engine/.../rest/catalog.py`) and the SDK
(`packages/screamingface/.../_engine/catalog.py`) only relay it. Landing relabeled
`screamingface-engine` → `aigateway` per the ticket's note.

**Escape-hatch note:** `SCREAMINGFACE_SKIP_PARAMETER_PREFLIGHT` does not exist on main
or in PR #870 — the ticket pre-describes a hatch that has not shipped. Fixing the root
cause here means it never ships; the "delete the hatch" closing step is vacuous and is
recorded as a coordination comment on the ticket instead.

## Design

- Only the would-be `profile_not_found` case (no profile AND no active connection AND
  plugin refuses chatless) becomes answerable. Pending (`409 profile_pending_auth`) and
  errored (`401 auth_required`) profiles keep today's refusals — a stored-but-broken
  target still points the human at the connect flow, and the SDK's retry semantics pin
  those codes.
- Keyless auth mode for the datasheet: `plugin.profileless_auth_mode()` if declared,
  else the first entry of `plugin.available_auth_modes()`. The published document
  already names its `auth_mode` in the context block, so the binding is visible, not a
  lie. Providers that allow a chatless profile keep the existing
  `resolved_auth_mode(None, None, plugin)` path unchanged.
- `_context_identity` already renders the no-target case as `anon`; `scope` and the
  `private, no-store` cache policy stay unchanged — the answer remains per-account on
  the wire even though its content is static.
- No credentialed data can leak: the document is composed from plugin-declared rules +
  the PUBLIC discovery runtime; no credential is ever in scope on this route.

## Planned changes

- `apps/aigateway/src/aigateway/routes/chat_credentials.py` — teach
  `_credential_target_for_chat` an opt-in `missing_target_ok` mode (default off; chat
  path unchanged) that returns `(None, None, ProfileDefaults())` instead of raising
  `profile_not_found`.
- `apps/aigateway/src/aigateway/routes/model_parameters.py` — resolve with
  `missing_target_ok=True`; when no target came back and the plugin refuses chatless,
  bind the keyless datasheet auth mode instead of calling `resolved_auth_mode`.
- Tests under `apps/aigateway/tests/` (extend the existing model-parameters route
  suite).

## Test plan

- RED: no profile, no connection, chatless-refusing provider → 200 with a full
  contract document; `context.auth_mode` = the plugin's first declared mode;
  `Cache-Control: private, no-store` still present. (Invariant: the datasheet needs no
  stored credential target.)
- Pending profile still 409 `profile_pending_auth`; errored profile still 401
  `auth_required`. (Invariant: a stored-but-broken target keeps pointing at the connect
  flow.)
- Connected profile answer unchanged (auth mode from the profile). (Invariant: the fix
  widens, never rewrites, the credentialed answer.)
- Chat dispatch with no profile still 404 `profile_not_found`. (Invariant: dispatch
  stays credentialed; only the datasheet went keyless.)

## Acceptance

- `GET /v1/model-parameters?model=<seeded id>` answers 200 on a store with zero
  profiles/connections for every seeded provider.
- All existing aigateway gates green (`uv run pytest`, ruff, pyright).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `routes/chat_credentials.py` (opt-in
  `missing_target_ok` on `_credential_target_for_chat`; chat path untouched),
  `routes/model_parameters.py` (`missing_target_ok=profile_name == "default"` +
  `_contract_auth_mode` keyless binding), `tests/unit/test_model_parameters_route.py`
  (flipped the pre-OME-1167 keyless-404 pin; added contract-equality and
  dispatch-still-404s invariants).
- **Commits:** see PR (single squash-merge commit).
- **Gates:** `run_gates.py aigateway --skip-append-only` ALL GREEN (ruff check + format,
  pyright, check_no_enterprise, pytest 17/17 in the route file, full suite green,
  coverage ≥80%).
- **Deviations:**
  - Prior test `test_missing_profile_reuses_chat_credential_resolution` was rewritten
    (append-only rule 5 exception): it pinned the exact "Before" behavior the ticket
    orders removed. Acknowledged via the gate runner's own `--skip-append-only` flag;
    every other prior test is untouched and green.
  - The ticket's SDK closing step (delete `SCREAMINGFACE_SKIP_PARAMETER_PREFLIGHT`) is
    vacuous: the hatch exists neither on main nor in PR #870 — the ticket pre-described
    a hatch that never shipped. Recorded as a coordination comment on `OME-1167` so
    OME-1098 does not ship it.
  - No separate `docs/spec`/`docs/plan` artifact: the ticket's Before/After is the spec
    and this ledger's Design section is the plan (bug-fix-sized unit).
