---
ticket: OME-1200
stack: aigateway
status: done
started: 2026-09-14
finished: 2026-09-14
---

# OME-1200 — Introduce the provider-access port with a Profile-backed read implementation

## Intent

Stage A1 of the adapter-first convergence (`OME-1138`). Introduce the boundary consumers will depend
on without knowing Profiles, and its first, Profile-backed implementation, with zero behaviour
change: routes, OpenAPI, HTTP status/detail, `X-Profile` semantics and the defaults → cache →
credential order stay byte-identical. Starts after Stage 0 (`OME-1198`, `OME-1199`); stops for
owner review; A2 needs a new authorisation.

## Planned changes

- New `apps/aigateway/src/aigateway/core/provider_access/` (each ≤450 lines): `__init__.py`,
  `_selector.py`, `_types.py`, `_ports.py`, `_auth_mode.py`, `_defaults.py`, `profile_backed.py`
  (resolve, repair, Connection fallback), `profile_authorize.py` (strategy, reauth URL,
  authorization, dispatch failure), `profile_defaults.py` (legacy-defaults reader). Bodies relocated
  per spec §3.4 rows 1–5.
- New `apps/aigateway/src/aigateway/routes/provider_access_http.py` — the refusal rendering table.
- `apps/aigateway/src/aigateway/main.py` — wire `app.state.provider_access` next to `profile_index`.
- `apps/aigateway/src/aigateway/routes/chat_credentials.py`, `routes/chat_profile_defaults.py` —
  compatibility shims re-exporting today's names (resolver shim renders refusals through the table).
- New tests under `apps/aigateway/tests/unit/core/provider_access/`.
- No route call-site, schema, store or Engine changes; existing tests untouched.

## Test plan (RED first)

- Selector normalisation table (`None`, `""`, whitespace, `default`, named; `explicit` flag).
- Port contract suite parameterised over a fake and the Profile-backed implementation: refusal
  matrix with legacy detail bodies; `defaults_for` never raises and returns `None` on store failure;
  two independent reads (no memoisation); `DATASHEET` absent-target rule; `ambient`/`none` kinds;
  `authorize` marks and evicts on credential errors; `record_dispatch_failure` marks and rewrites
  `reauth_url`; `UnsupportedAuthMode` raised by auth-mode/authorize, never by `resolve`.
- `context_stamp` parity pin (`prof:`/`conn:`/`anon` strings byte-identical).
- A fake that returns a target for an unsupported explicit selector under the reject policy fails
  the contract.
- Shim parity: by-path importers and `routes.chat` namespace patches keep working.

## Acceptance

- Whole gateway suite green with zero test edits; PostgreSQL lane green; consumer gates (Engine,
  SDK, UI) run explicitly and green; OpenAPI export byte-identical to HEAD; all new files ≤450 lines.

## Outcome

- **Actual files (all in `apps/aigateway/`):**
  - New `src/aigateway/core/provider_access/`: `__init__.py` (104 lines, public facade),
    `_types.py` (206), `_selector.py` (49), `_ports.py` (128), `_auth_mode.py` (102),
    `_defaults.py` (70), `profile_defaults.py` (44), `profile_authorize.py` (219),
    `profile_backed.py` (278). Bodies relocated from `routes/chat_credentials.py`,
    `routes/chat_profile_defaults.py`, `routes/model_parameters.py` (`_context_identity`,
    `_contract_auth_mode`) and the store half of `routes/chat_dispatch.py`.
  - New `src/aigateway/routes/provider_access_http.py` (133) — `render_refusal` table +
    `refusals_as_http()`; 100% covered.
  - `src/aigateway/routes/chat_credentials.py` 483 → 122 lines (shim: same nine names, same
    signatures; pure helpers re-exported by identity); `routes/chat_profile_defaults.py` 143 → 121
    (`profile_defaults_for_key` delegates; `_parameter_rejection_exception` untouched);
    `src/aigateway/main.py` +3 lines (import + `app.state.provider_access` next to `profile_index`).
  - New tests `tests/unit/core/provider_access/`: `_provider_access_fake.py` (330),
    `_provider_access_harness.py` (268), `test_provider_access_selector.py`,
    `..._resolve_contract.py`, `..._authorize_contract.py`, `..._http.py`, `..._helpers.py`,
    `..._shims.py`, `..._port_shape.py` — 170 tests, the contract suites parameterised over the
    fake and the real implementation.
  - No route call site, schema, store, Engine or existing-test change (append-only check green).
- **Commit:** `feat(aigateway): introduce provider access port` (this commit).
- **Gates:**
  - `uv run .claude/scripts/run_gates.py aigateway --base 17048f5d`: append-only check, ruff check,
    ruff format --check, pyright, check_no_enterprise ✓; the pytest gate's first run (five lanes
    sharing the CPU) had 4319 passed / 1 failed / 58 skipped, 92.73% — the one failure is the
    pre-existing bcrypt timing flake `test_login.py::test_unknown_user_timing_close_to_wrong_password`
    (1 of 3 isolated reruns fails on the same tree; recorded in the 2026-09-09 baseline).
    Standalone `uv run pytest --cov=aigateway -q`: **4320 passed / 58 skipped, 93%** (Stage 0 had
    4190 → +130). Standalone `run_gates.py aigateway --base 17048f5d` re-run (13:17–13:22, no
    parallel lanes): **ALL GATES GREEN**, exit 0 — the timing flake did not recur.
  - PostgreSQL lane `AIGW_TEST_PG=1 uv run pytest -m needs_postgres -q`: 16 passed, 5 failed — all in
    `tests/integration/test_cache_snapshot_upload_postgres.py` on `pg_dump` exit 1 (local pg_dump
    15.13 vs pinned `postgres:16-alpine`); identical against a `git archive HEAD` export → pre-existing,
    environmental, unrelated.
  - Consumer gates: Engine `run_gates.py screamingface-engine --base 17048f5d` ALL GREEN;
    `packages/url4` ALL GREEN; `packages/screamingface` ALL GREEN after `uv sync --extra notebook`
    (CI's own step; without it pyright fails on `ipywidgets`); `apps/aigateway-ui` `npm ci` + lint +
    typecheck + `test:ci` green (statements 89.88%).
  - OpenAPI: `create_app().openapi()` (sorted JSON) byte-identical to the HEAD export, 78 065 bytes.
  - New-module coverage: 96–100% each; `chat_credentials.py`/`chat_profile_defaults.py` 100%.
- **Deviations:**
  - `tortoise-dev` companion not invoked: the unit adds no model, queryset, migration, transaction
    or lifespan change — the port reads through the existing stores (assessed at DESIGN).
  - Temporary duplication until A2 (call sites untouched by instruction): the store half of
    `chat_dispatch._dispatch_failure_response` vs `record_dispatch_failure`; `model_parameters.
    _contract_auth_mode`/`_context_identity` vs `contract_auth_mode`/`context_stamp`. Parity pinned by
    `test_provider_access_helpers.py` and `test_provider_access_shims.py`.
  - The "profile index unreadable before the cache stage" warning now logs under
    `aigateway.core.provider_access.profile_defaults` (was `...routes.chat_profile_defaults`); text
    unchanged; no test pins the logger name.
  - `main.py` grew 462 → 465 lines; it was already above the 450 limit at HEAD (wiring only).
  - Hardening beyond pure relocation: `Authorization.headers` is excluded from `repr` so a traced
    value never prints a Bearer token (equality unchanged).
  - Shim `_credential_target_for_chat` maps `missing_target_ok=True` → `ResolvePolicy.DATASHEET`; the
    port additionally requires the DEFAULT selector. The only caller (`model_parameters.py`) passes
    True exactly when the name is `default`, so nothing observable changes.
  - `touch_last_used` now runs before (not after) the body is sealed — both complete before return.
- **Wisdom review:** no secret logged; no fail-open path (strategy-less api_key target still refused,
  missing credential still refused without marking, rejected credential still marks); the broad
  `except` exists only at the documented pre-cache fail-safe boundary; hexagonal check green (core
  imports no route/plugin — pinned by a test). Stopped here for owner review per instruction: A2–A4
  and any backing migration are NOT started.

## Review fixes (2026-09-14, owner findings 1–6) — DONE

Owner review of the A1 diff returned six findings; fixed in this same unit before the commit.

- **F1 P1 port ≠ spec §3.3.** `_ports.py` gains `auth_mode(target, plugin)`,
  `contract_auth_mode(target, plugin)`, `availability(account_id) -> tuple[AvailabilityRow, ...]`;
  `record_dispatch_failure(target, status, detail, *, plugin)`. The Profile-backed class delegates
  the two mode operations to the existing helpers; `availability` is a fail-closed placeholder
  (`NotImplementedError`) because its body and golden tests are A3 by spec/plan — declared now so
  the port is complete, not started. `status` is carried, not consumed (the status gate stays in
  the route per spec op 5).
- **F2 P1 substitution.** `provider_access_for(app)` returns whatever `app.state.provider_access`
  holds and creates the Profile-backed implementation only when absent; return type `ProviderAccess`.
- **F3 P2 admin shape.** `ProviderCredentialAdmin` redeclared per spec ops 7–9: `tuple` listing,
  `set_api_key(account_id, provider, *, raw_api_key, legacy_name, defaults)`,
  `delete(account_id, provider, *, legacy_name)`. Still declared only.
- **F4 P2 side effects.** Harness gains `evicted()`, `invalidated()`, `last_used(connection_id)`;
  new contract tests assert eviction, session invalidation (and its ABSENCE for a missing blob),
  and the last-used touch for `authorize` and `record_dispatch_failure`, over both witnesses. The
  harness is split (`_provider_access_fake.py` + `_provider_access_harness.py`) to stay ≤450 lines.
- **F5 P2 touch order.** Spec op 4 places `touch_last_used` inside `authorize` and makes sealing
  a separate pure step, so the touch now precedes sealing by construction. Declared explicitly:
  WHY anchor in `authorize`, pinned by the touch contract test, recorded here and in Linear.
  Restoring the legacy order would need a spec change (owner call, noted in the report).
- **F6 P3 annotations.** Backing swap is Stage B (not A4) in `__init__.py` and `profile_backed.py`;
  shadow Connection is D14 (not D18) in the gateway characterisation docstring; the Engine
  characterisation docstring no longer ties the Local ambiguity rule to A3/A4 availability.
- **Tests:** new `test_provider_access_port_shape.py`; additions to the authorize contract and shim
  suites. Existing (HEAD) tests untouched; my own uncommitted A1 tests may be extended.
- **Acceptance:** RED first; full aigateway gate green; Engine gate re-run (docstring-only change).

### Review-fixes outcome

- **Files changed:** `core/provider_access/_ports.py` (77 → 128 lines; both Protocols
  `@runtime_checkable`; seven read operations, three admin operations per spec §3.3),
  `profile_backed.py` (259 → 278; `auth_mode`/`contract_auth_mode`/`availability` methods, new
  `record_dispatch_failure` shape, `provider_access_for` honours the wired object, Stage B note),
  `profile_authorize.py` (206 → 214; `status` carried, WHY anchor on the touch order),
  `__init__.py` (Stage B note). Tests: harness split into `_provider_access_fake.py` (314) +
  `_provider_access_harness.py` (249) with `evicted()/invalidated()/last_used()`; new
  `test_provider_access_port_shape.py` (171); authorize contract 197 → 302 (seven side-effect
  tests + `status` in the record helper); shim suite 197 → 240 (two substitution tests).
  Docstring-only edits in the two Stage 0 characterisation modules (D14; Local rule wording).
- **RED evidence:** 17 failures before the fix (port shape ×9, substitution ×1, Profile-backed
  `record_dispatch_failure` shape ×6, mode ops via the port ×1); the side-effect assertions were
  green on both witnesses at once — the behaviour existed, only the assertions were missing.
- **Gates:** `run_gates.py aigateway --base 17048f5d` ALL GATES GREEN (append-only, ruff, format,
  pyright, no-enterprise, pytest ≥80%); provider-access suites 166 passed (130 → +36, parametrised);
  `run_gates.py screamingface-engine --base 17048f5d` ALL GATES GREEN after the docstring edit.
  OpenAPI export content-identical to HEAD (the exporter's trailing newline is the only byte).
- **F5 disposition:** the touch order is now declared (WHY anchor + pinned test + this ledger);
  restoring the 17048f5d order would move `touch_last_used` out of `authorize`, i.e. a spec §3.3
  op 4 change — the owner's call, not made here.
- **F1 disposition:** `availability` is declared on the port and on both witnesses; the
  Profile-backed body raises `NotImplementedError` until A3 delivers it with the golden tests (no
  caller exists before A4). The fake implements the spec aggregation over its dicts.
- **Commit:** included in `feat(aigateway): introduce provider access port`.

## Review fixes, round 2 (2026-09-14, owner findings on F4/F5) — DONE

- **F4 residual.** The fake leaves a Connection `active` on a MISSING blob while the Profile-backed
  body marks it `error` (both evict; neither invalidates). New contract case over both witnesses:
  missing Connection blob → eviction, Connection `error`, no invalidation, no touch. Fake fixed to
  mark the Connection. The existing missing-blob test becomes Profile-specific in name and text.
- **F5 residual + decision.** Owner recommendation accepted: `touch_last_used` stays inside
  `authorize`; touch-before-sealing is an explicit parity exception. Minimal hardening: normalise
  `headers = dict(headers)` BEFORE the touch so a malformed strategy result cannot leave a false
  `last_used`. New contract case (harness `malform_credential`): malformed credential result →
  `TypeError`, no touch, Connection still `active`. WHY anchor and this ledger updated.
- **Acceptance:** RED first (fake fails the missing-Connection case; Profile-backed fails the
  malformed-result case); full aigateway gate green.

### Round-2 outcome

- **Files:** `core/provider_access/profile_authorize.py` (214 → 219): `headers = dict(raw_headers)`
  before the touch with an INVARIANT anchor; the WHY anchor now records the owner-accepted parity
  exception. Tests: `_provider_access_fake.py` (314 → 330: missing Connection blob marks the row,
  `malformed` flag raises before the touch, `malform_credential`), `_provider_access_harness.py`
  (249 → 268: `malform_credential` on the Protocol and a `_MalformedStrategy`),
  `test_provider_access_authorize_contract.py` (302 → 336): missing-blob test renamed
  Profile-specific and asserting the Profile stays authenticated; new
  `..._missing_connection_credential_evicts_and_marks_the_connection_without_invalidating` and
  `..._malformed_credential_result_never_touches_last_used`.
- **RED evidence:** 3 failures before the fix — fake left the Connection `active` on a missing blob;
  both witnesses touched (or would have) before validating the strategy result.
- **F5 decision (owner, 2026-09-14):** `touch_last_used` stays inside `authorize`; touch-before-
  sealing is an explicit parity exception vs 17048f5d. Residual observable: a provider-produced
  body with a non-mapping `extra_headers` fails in the pure sealing step after the touch; caller
  bodies of that shape are rejected by the hardening layer earlier.
- **Checks:** provider-access suites 170 passed (166 → +4); ruff, format, pyright clean on the
  package and its tests. Full `run_gates.py aigateway --base 17048f5d` after round 2: **ALL GATES
  GREEN**, exit 0. Engine untouched this round (its gate stayed green from round 1).
- **Commit:** included in `feat(aigateway): introduce provider access port`.

## Follow-up (2026-09-15) — `OME-1204`

The module and helper names recorded above are the names this unit shipped with; they are kept here
as history. By owner decision (spec §8 D19: no provider-access file name begins with `_`,
`__init__.py` excepted) the five package halves and the two test helpers were renamed in
`OME-1204`, a separate rename-only unit: `_types.py → types.py`, `_selector.py → selector.py`,
`_ports.py → ports.py`, `_auth_mode.py → auth_mode.py`, `_defaults.py → defaults.py`;
`_provider_access_fake.py → provider_access_fake.py`, `_provider_access_harness.py →
provider_access_harness.py`. Ledger: `docs/work/2026-09-15-OME-1204-rename-provider-access-modules.md`.
