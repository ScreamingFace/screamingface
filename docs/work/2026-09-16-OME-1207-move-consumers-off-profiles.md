---
ticket: OME-1207
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-09-16
finished: 2026-09-17
---

# OME-1207 — Move the A2 in-process consumers onto the provider-access port

## Intent

Stage A2 of OME-1138 (adapter-first convergence). A1 (`OME-1200`/`OME-1204`) introduced
`core/provider_access/` — the port, the Profile-backed implementation and the one HTTP refusal
table — but left every route call site untouched behind two re-export shims. This unit moves the
four in-process consumers onto the port itself, so the backing swap at Stage B (D11) changes no
route:

- chat credential resolution (`routes/chat.py`),
- model parameters / datasheet defaults and the auth-mode path (`routes/model_parameters.py`),
- model admission (`routes/model_admission.py`),
- dispatch-failure marking (`routes/chat_dispatch.py`).

D20 vocabulary binds: `Connection` is the final resource noun, `provider access` is the boundary,
`legacy Profile` is the compatibility surface. `Provider Account` is not introduced.

## Planned changes

Production:

- `src/aigateway/routes/chat.py` — parse `X-Profile` once into a `Selector`; resolve ONE
  `CredentialTarget` through `provider_access_for(app)`; `auth_mode(target, plugin)`;
  `authorize(...)` + `apply_authorization` in place of `_inject_credentials`; carry `target`
  (not `profile`/`connection`) into the dispatch-failure helpers.
- `src/aigateway/routes/model_parameters.py` — delete `_context_identity` (replaced by
  `target.context_stamp`) and `_contract_auth_mode` (replaced by the port's
  `contract_auth_mode`); resolve under `ResolvePolicy.DATASHEET`; `execution_access` from
  `target.kind == "stored"`.
- `src/aigateway/routes/model_admission.py` — `_credential_verdict` catches the typed refusals
  (`TargetReauthRequired`, `TargetPending`) instead of re-reading HTTP detail codes; relayed code
  strings stay byte-identical.
- `src/aigateway/routes/chat_dispatch.py` — `_dispatch_failure_response` takes the target and
  calls `record_dispatch_failure`; drops the `Profile`/`OAuthConnection` imports.
- `src/aigateway/core/provider_access/profile_backed.py` — remove `legacy_target_parts` /
  `target_from_legacy` (the "dies at A2" shim support) once nothing imports them.
- `src/aigateway/routes/chat_credentials.py` — deleted when no test imports it; otherwise kept
  with an explicit removal point.

Tests:

- NEW `tests/unit/core/provider_access/test_provider_access_import_boundary.py` — the migrated
  consumers may not import `Profile`, `ProfileState`, `ProfileIndexStore` or `OAuthConnection`.
- NEW datasheet-equivalence + admission-relay pins.
- Re-expressed at the port seam (the two suites the plan names):
  `tests/unit/openrouter/test_openrouter_routing_policy_route_rejections.py` (patches
  `chat._inject_credentials`) and `tests/unit/usage_accounting/test_chat_route_accounting.py`
  (patches `chat._credential_target_for_chat`).

## Test plan

RED first, in this order:

1. Import boundary: the four migrated modules import none of the four legacy symbols; the
   allowed owners (`core/provider_access/`, `core/profile_*`, `core/oauth/*`, `routes/auth.py`,
   `routes/admin.py`, `routes/oauth_connections.py`, bootstrap, `plugin_base`) are unaffected.
2. `DATASHEET` equivalence: a target-less DEFAULT selector answers; a target-less NAMED selector
   still 404s — the old `profile_name == "default"` rule, now carried by the policy.
3. Admission relay still emits `auth_required` / `profile_pending_auth` with today's messages.
4. Dispatch-failure marking goes through `record_dispatch_failure` (error row marked, strategy
   evicted, session invalidated, `reauth_url` rewritten).
5. Every existing HTTP pin for chat, model parameters, admission and cache behaviour stays green
   and unmodified.

## Acceptance

- The four consumers reach credentials only through `provider_access`; no direct legacy Profile
  import remains outside the documented owners.
- HTTP behaviour byte-identical: status codes, detail bodies, `reauth_url` shapes, `Vary`,
  `Cache-Control`, cache hit/miss ordering.
- OpenAPI export byte-identical against the branch base.
- Full AIGateway gate green; `git diff --check` clean.
- Any remaining compatibility import carries an explicit removal point.
- Nothing in A3 (admin interface / availability) is started.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned for the four consumers, with two exceptions (below).
  Production — `routes/chat.py`, `routes/chat_dispatch.py`, `routes/model_parameters.py`,
  `routes/model_admission.py` migrated onto the port; `routes/chat_credentials.py` and
  `core/provider_access/profile_backed.py` keep their shim surface with a corrected removal point.
  Tests — NEW `tests/unit/core/provider_access/test_provider_access_import_boundary.py`;
  re-expressed `test_provider_access_helpers.py`, `test_provider_access_shims.py`,
  `test_openrouter_routing_policy_route_rejections.py`, `test_model_execution_access.py`,
  `test_chat_route_accounting.py`.
  Docs — this ledger, `docs/tasks/2026-09-16-OME-1207-move-consumers-off-profiles.md`,
  and the A2 status rows in the OME-1138 plan.
- **Commits:** `AIGateway: move consumers onto provider access` (`Refs: OME-1207`). Not pushed.
- **Gates:** `run_gates.py aigateway --base 0c0abfcf` — **NOT a clean pass. The append-only check
  is RED by design** (see Deviations 1); the owner accepted that deviation for OME-1207 only, and
  it was not waived, silenced, or worked around. The remaining five gates are green: ruff, ruff
  format, pyright, `check_no_enterprise.py`, `pytest --cov=aigateway --cov-fail-under=80`.
  Independently verified totals: focused changed-seam tests 100 passed; full suite
  **4463 passed / 58 skipped, coverage 92.69 %**. Import boundary 7/7. OpenAPI byte-identical to
  the branch base (both trees exported through the same interpreter and compared with `cmp`).
  `git diff --check` clean.
- **Deviations:**
  1. **Five prior suites modified, not two.** The plan named two
     (`test_openrouter_routing_policy_route_rejections.py`, `test_chat_route_accounting.py`).
     Three more were forced by deletions the plan itself mandates: the suites imported or patched
     `model_parameters._context_identity` and `model_parameters._contract_auth_mode`, which A2
     deletes, so they were collection errors and `AttributeError`s rather than policy choices.
     Each was re-expressed at the port seam with coverage preserved or strengthened — the
     context-stamp pin now asserts the byte formula itself rather than agreeing with a helper that
     could have drifted with it, and the accounting pin now raises the typed refusal so it
     exercises the real edge table instead of hand-building the HTTP shape it asserts on.
     This is an SDLC rule 5 Confidence-Gate item. **ACCEPTED BY THE OWNER on 2026-09-17, for
     OME-1207 only** — explicitly as an accepted deviation, not as a clean gate pass. The official
     `run_gates.py aigateway --base 0c0abfcf` stays red on append-only; a later unit must earn its
     own decision rather than cite this one.
  2. **`legacy_target_parts` / `target_from_legacy` survive A2.** A1 marked them "dies at A2" on
     the assumption that migrating the four call sites would orphan `routes/chat_credentials.py`.
     No route imports that module any more, but the A1 shim suite still does, and a prior suite is
     not deleted to make a removal tidy. Removal point corrected to Stage E (OME-1209) in both files.
  3. **`core/admin_schemas.py` stays on the owners allow-list.** `AdminProfileOut.state` is typed
     `ProfileState`, so migrating it would change OpenAPI — forbidden here, and it belongs to the
     A3 admin group with `routes/admin.py`.
  4. **Scope note (reported, not acted on):** the Linear description lists provider
     availability/listing paths and admin route bodies. Both are A3/A4 in the plan and were left
     untouched, per the unit's non-goals.
