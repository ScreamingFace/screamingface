---
ticket: OME-1138
status: draft   # adapter-first re-plan; no execution, task or publication approval is inferred
created: 2026-09-09
updated: 2026-09-24
spec: ../spec/2026-09-09-OME-1138-converge-connections.md
---

# Plan: introduce the provider-access boundary first, then transition the backing

Input: the adapter-first [spec](../spec/2026-09-09-OME-1138-converge-connections.md) revision of
2026-09-13, the owner's adapter-first investigation brief and clarification (an adapter will exist;
Profiles stay for now and are reached only through it; the later step is a backing/authority choice
behind the boundary), and the retained P0/P1 history. D2 (full defaults REMOVE at an explicit cutover)
stands; D20 settles the naming
(`Connection` is the final resource noun, `provider access` is the boundary, `Profile` is legacy
compatibility, and `Provider Account` is not introduced). This plan itself authorises no
runtime code, catalog write, migration, Linear mutation, staging or push; Stage 0 and A1 were
separately approved and executed on 2026-09-14.

Work on branch `OME-1138-converge-connections` started at `17048f5d` (owner exception: shared
checkout, never `main`). `origin/main` was at `c1c92562` during the design pass (see spec §1 for the
three affected anchors). Do not rebase, merge, reset, stash or clean without an instruction;
foreign uncommitted files stay untouched. The previous first units S1–S3 are replaced by Stage 0
and A1–A3 (spec §9); D7 was re-approved and the matching issues were filed before code started.

## 1. Stage status

| Stage | Gate | Status, 2026-09-24 |
| --- | --- | --- |
| P0 baseline | G0 | done 2026-09-09 at b47853ea (gates, consumer/meta maps); anchors re-verified at 17048f5d in this pass; gates not rerun |
| P1 design | G1 | **revised to adapter-first**: consumer evidence, adversarial checks and review feedback incorporated; spec §3–§9 written; D11–D18 and the D7 conflict presented (their current status: spec §8); not approved |
| Stage 0 characterisation | G1 | **done** as U0 (gateway) and U0e (Engine); commits `48fa1d78`, `c7d767f7` |
| A1 port + Profile-backed read implementation | G2a | **done** as U1; review findings closed; module names follow D19 (`OME-1204`, 2026-09-15); stop before A2 |
| Naming decision | G2b precondition | **done** as `OME-1210` (D20): final domain/API/UI noun is Connection; provider-access is the boundary; Profile is legacy compatibility; Provider Account is not introduced as a resource name |
| A2 in-process consumers | G2b | **merged** as U2 (`OME-1207`, PR #981, `248b0b6d`, 2026-09-17): four consumers on the port; at implementation: import boundary 7/7, full suite 4463 passed / 58 skipped at 92.69 % coverage, OpenAPI byte-identical to `0c0abfcf`; its append-only check was red by an owner-accepted Confidence-Gate deviation scoped to `OME-1207` only (five prior suites re-expressed at the port seam) |
| A3 admin interface + management shells | G2c | **merged** as U3 (`OME-1230`, PR #992, `a78d58da`, 2026-09-21): the Profile management routes sit behind the provider-credential admin boundary |
| A4 Hosted Engine on the availability successor | G3 | **merged** in two units (D15 and D17 decided 2026-09-14): U4 (`OME-1244`, PR #1006, `2da45896`, 2026-09-21) publishes the caller-scoped `GET /v1/provider-access` listing; U4e (`OME-1245`, PR #1007, `54fa8673`, 2026-09-22) moves the Hosted Engine listing onto it |
| B backing transition | G4 | **merged** as `OME-1208` (PR #1029, `7cff8a56`, 2026-09-23) under D11 (a), D14 and D16, decided 2026-09-22 (design PR #23): the `provider_credential_slots` pair marker, the Connection-backed implementations and the backfill tooling (S1/S2'/S4); Profile storage, routes and schemas stay until Stage E (`OME-1209`) |
| C defaults cutover (D2) | G5a | **UI done** as `OME-1322` (PR #1043, `21832443`): the console sends only `{ "api_key" }`. **Gateway implemented locally** as `OME-1323` (2026-09-24, branch `OME-1323-remove-profile-defaults`; not committed, no PR): chat no longer reads or merges stored defaults, the five writers answer a present `defaults` (even `null`) with 422 `defaults_not_accepted`, cache keys byte-identical (no revision bump, no reset). The running console must use the key-only payload before the gateway refusal reaches dev |
| D selector sunset and carriers (D4) | G5b | not started; needs the date, disposition and env audit |
| E retirement and cleanup | G6 | not started; needs D6 |
| S13 catalog | M0 | additive text possible after M0; successors at D/E |

## 2. Unit decomposition (D7 re-approved 2026-09-14 for U0/U0e/U1; epic = OME-1138)

One landing label per issue; each unit is one SDLC unit with its own ledger. Creation or reuse in
Linear needs explicit permission; this table is not evidence that issues exist.

| # | Title (imperative) | Landing | Stage | Depends on |
| --- | --- | --- | --- | --- |
| U0 | `OME-1198` — Pin the current credential-selection behaviour with characterisation tests | `aigateway` | 0 | G1 |
| U0e | `OME-1199` — Pin the worker's ambient `AIGATEWAY_PROFILE` inheritance and the in-process pop | `screamingface-engine` | 0 | G1 |
| U1 | `OME-1200` — Add the provider-access port and the Profile-backed read implementation behind the existing routes | `aigateway` | A1 | U0 |
| U1n | `OME-1204` — Rename the provider-access modules and test helpers without leading underscores (D19; rename-only) | `aigateway` | A1 follow-up | U1 |
| U1t | `OME-1210` — Decide final provider identity naming (D20; docs/Linear only) | `aigateway` | A1 follow-up / A2 precondition | U1, U1n |
| U2 | `OME-1207` — Move chat, model parameters, admission and dispatch marking onto the provider-access port | `aigateway` | A2 | U1, U1n, U1t |
| U3 | Add the provider-credential admin interface and reduce the Profile management routes to shells | `aigateway` | A3 | U1, U1n, U1t |
| U4 | Publish the backing-neutral availability listing | `aigateway` | A4 | U3, D15, D17 |
| U4e | Move the Hosted Engine listing onto the availability successor | `screamingface-engine` | A4 | U4 |
| S1 | Add the provider-credential slot store with generation fencing and a locator-authoritative strategy factory | `aigateway` | B (D11 a) | D11, D14 |
| S2' | Add the pair-marker authority routing and the Connection-backed implementations of both interfaces | `aigateway` | B (D11 a) | S1 |
| S4 | Build the secret-aware backfill tool with dry-run, journal, atomic authority fencing and tested R1 rollback | `aigateway` | B (D11 a) | S1, S2' |
| B' | Provider-account aggregate, migration and implementations (replaces S1/S2'/S4) | `aigateway` | B (D11 b) | D11, D14 |
| S7a | `OME-1322` — Drop the Admin UI defaults fieldset at the cutover (done, PR #1043) | `aigateway` (UI stack gates) | C | D2 |
| S7 | Move the Admin UI list/delete and its key-only attach/replace call onto the admin successor | `aigateway` (UI stack gates) | D18 | U3, D18, S7a |
| S11 | Activate the defaults REMOVE and the selector rejection policy | `aigateway` | C / D | B, D16, D4 date |
| S6 | Retire the Engine selector carrier with old/new worker and accepted-job compatibility tests | `screamingface-engine` | D | S11 disposition |
| S8 | Map any new gateway codes in the SDK with unchanged retry semantics | `py-screamingface` | D | S11 |
| S9 | Retire URL4 `JobRunner.schedule(profile=...)` after compatible Engine changes | `url4-python-sdk` | D | S6 |
| S12 | Remove the Profile runtime domain, routes, bootstrap path and index writes; guarded legacy blob cleanup | `aigateway` | E | S11, D6 |
| S13 | Catalog text, successors and tooling retirement list | design repository, not this repo | A1–E | M0 |

S10 stays excluded (Desktop output untouched). S5 is U4e. S1/S2'/S4 and B' are alternatives
selected by D11. U0/U0e may be folded into U1 if the owner prefers one first unit.

## 3. Per-stage work, tests first

### Stage 0 — characterisation (no `src` change)

RED tests that must pass at HEAD: Profile named `default` wins over active Connections when both
exist; whitespace-only `X-Profile` behaves as absent; after `DELETE` of a Profile the same selector
reaches the shadow Connection created by the Profile OAuth completion (documents current behaviour
and its risk); a persistent index fault at the resolver escapes unhandled (documents today's
outcome); Engine `_child_env` inherits an ambient `AIGATEWAY_PROFILE` while the in-process runner
pops it; Local Engine 409 on mixed non-active managed rows. Acceptance: green with `apps/*/src`
untouched; the tests are the parity net for A1.

### A1 — port and Profile-backed read implementation

1. RED: selector normalisation table (`None`, `""`, whitespace, `default`, named); port contract
   suite parameterised over a fake and the Profile-backed implementation (refusal matrix with
   legacy detail bodies; `defaults_for` never raises and returns `None` on store failure; two
   independent reads; `DATASHEET` absent-target rule; `ambient`/`none` kinds; `authorize` marks
   and evicts on credential errors; `record_dispatch_failure` marks and rewrites `reauth_url`);
   `context_stamp` parity pin; a fake returning a target for an unsupported explicit selector under
   the reject policy fails the contract.
2. Implement `core/provider_access/` (port, types, selector, defaults application, a composable legacy-defaults
   reader, Profile-backed read and dispatch modules, each ≤450 lines; layout per spec §3.1) by
   mechanical relocation per spec §3.4; the shim resolver renders refusals through the edge table so
   by-path importers still see `HTTPException`; wire
   `app.state.provider_access` next to `profile_index`; add the HTTP rendering table; turn
   `routes/chat_credentials.py` and `routes/chat_profile_defaults.py` into re-export shims (three
   test modules import by path, one scans the module object; one patches `ProfileIndexStore.get` on
   the class, so the adapter must call the class method; the two `routes.chat` namespace patches
   keep working at A1 because `chat.py` still binds the names). No route call-site edits, no new route, no schema or store change.
3. Gates: `run_gates.py aigateway` (ruff, format, pyright, import guard, pytest with coverage) and
   the PostgreSQL lane. OpenAPI export byte-identical (read-only catalog tools). Files ≤450 lines.
4. Evidence for G2a: full gateway suite green unmodified (baseline 4104 passed; the pre-existing
   bcrypt timing failure excepted); consumer lanes (Engine, SDK, UI) run explicitly even though
   they do not change.

### A2 — in-process consumers

RED first: import-boundary test (`Profile`, `ProfileState`, `ProfileIndexStore`, `OAuthConnection`
importable only from `core/provider_access/`, `core/profile_*`, `core/oauth/*`, `routes/auth.py`,
`routes/admin.py`, `routes/oauth_connections.py`, bootstrap and `plugin_base`); `DATASHEET`
equivalence with the old `profile_name == "default"` rule; admission relay still emits the legacy
code strings. Then rewrite `routes/chat.py`, `model_parameters.py`, `model_admission.py`,
`chat_dispatch.py` against the port, deleting the three normalisations, `_context_identity` and the
target inspection in the contract auth-mode helper. Optional: one `seed_credential` fixture helper
adopted mechanically by the 18 feature suites that seed a Profile as a precondition; the 4
storage-invariant, 2 facade and 1 bootstrap suites (spec §2 tests row) are never re-pointed to it. Re-express the two suites that patch
`aigateway.routes.chat._inject_credentials` (openrouter rejections) and
`aigateway.routes.chat._credential_target_for_chat` (usage accounting) against the port seam — the
only test edits this unit makes. Acceptance: HTTP pins green; scope, Vary, codes and `reauth_url`
shapes unchanged; shims deleted only when no test imports them.

**As built (`OME-1207`, 2026-09-16).** Two corrections to the paragraph above, both consequences of
deletions it mandates rather than changes of intent:

- **Five suites were re-expressed, not two.** `test_provider_access_helpers.py`,
  `test_provider_access_shims.py` and `test_model_execution_access.py` imported or patched
  `model_parameters._context_identity` / `_contract_auth_mode`, which this unit deletes, so they
  failed at collection or on `AttributeError`. Each moved to the port seam with coverage preserved
  or strengthened. The append-only gate flags all five; the decision is the owner's.
- **The shims survive.** No route imports `routes/chat_credentials.py` any more, but the A1 shim
  suite does, so it and its `legacy_target_parts` / `target_from_legacy` support in
  `profile_backed.py` keep their surface; both files now name Stage E (`OME-1209`) as the removal
  point instead of A2. `core/admin_schemas.py` also stays a documented owner: `AdminProfileOut.state`
  is typed `ProfileState`, so migrating it would change OpenAPI — it moves at A3 with `routes/admin.py`.

The `seed_credential` fixture helper was NOT adopted: it is optional, and touching 18 further feature
suites would widen the append-only surface for no boundary gain. The three normalisations,
`_context_identity` and the contract auth-mode target inspection are deleted as specified.

### A3 — admin interface and management shells

RED first: OME-307 ordering re-asserted at the adapter seam (index CAS first, blob second, one
transaction, delete-wins); wholesale defaults replacement pin; tenant listing JSON parity;
availability builds no strategy and triggers no refresh; both conflict contracts re-asserted
(CAS-retry exhaustion → 503 `profile_index_conflict`; superseded publish → 409 `profile_conflict`);
`availability` golden-equivalent to the Engine `decode_profile_statuses` rule over recorded
`/v1/auth/profiles` bodies (the gateway listing is raw today; the rule lives only in the Engine).
Then move the bodies of
`upsert_api_key_profile` and `delete_profile_for_account` into the Profile-backed admin module
(routes keep shells), implement `availability`, wire `app.state.provider_credential_admin`. PATCH,
OAuth start/callback/refresh and bootstrap stay direct store owners. Acceptance: existing race,
API-key and admin route suites green unmodified, PostgreSQL lane included; `routes/auth.py`
shrinks and gains no logic.

### A4 — availability successor and Hosted Engine (after D15, D17)

Gateway: the successor listing route over `availability` (scoping tests; no defaults, ids, labels or
secrets in the body; `private, no-store`; inbound `X-Profile` proven non-selecting). Engine: hosted
branch reads the successor, decoder replaced, `listing_source` replaced by the D15 mutability rule,
`profile_availability.py` deleted, header no longer forwarded on that call. Acceptance: per-fixture
equality with today's aggregation; hosted mutations still refused before I/O; Engine
`/v1/connections` DTO field set unchanged (SDK strict decoder untouched); Engine layering gate;
`screamingface-e2e-replay` lane still green (it pins 404 `profile_not_found`).

### B, C, D, E

Preconditions and acceptance per spec §5–§7. B starts only after D11 and D14; option (a) executes
S1 → S2' → S4 with the retained E/B/C migration, R0–R4 authority table and quarantine rules;
option (b) executes B' under the same discipline (dry-run, journal, quarantine, tested rollback,
protected metadata mapping). C removes defaults per spec §3.7 with a measured cache impact and
rejects legacy writes carrying defaults; it lands UI first (`OME-1322`), then gateway
(`OME-1323`), and keeps `defaults_for`, `apply_defaults`, `should_apply_profile_default` and
`CredentialTarget.defaults` declared without a production caller until E. D enables the reject policy only after the provenance
census, drained or dispositioned accepted work and the worker env audit; S6 before S9; SDK and e2e
pins change in the same release train as any code rename. E follows D6 with reference-safe cleanup
and the tooling retirement list.

### Current-source preservation checks (unchanged obligations)

- Model parameters: keyless default datasheet and provider-declared mode; admission does not adopt
  the exception (`routes/model_parameters.py:113-250`, `routes/model_admission.py:93-169`;
  `tests/unit/test_model_parameters_route.py:99-149,256-301`).
- Chat: cache hits precede credential resolution for missing, pending and errored targets
  (`routes/chat.py:291-377`; SDK `tests/e2e/harness/cache_seeded.py:13-29,144-160`). Until stage C:
  unreadable defaults bypass the cache and there is one effective-body merge. From stage C
  (`OME-1323`) chat reads and merges no stored defaults, so an unreadable profile index no longer
  bypasses the cache and a hit reads no index at all.
- Tavily retrieval lane: no credential resolution or identity keying; `tests/unit/tavily_retrieval/`.
- Correlation: `gateway_call_id`, streaming lifetime and redaction outside Taxonomy
  (`tests/unit/test_call_context.py`); tracing added on `origin/main` must keep working after rebase.
- Engine client: 30 s catalog timeout, one retry on GET timeout only; empty 2xx retryable, invalid
  JSON permanent (`tests/unit/test_catalog_aigateway.py:207-260`, `test_empty_gateway_response.py`,
  `tests/integration/test_gateway_failure_report.py`).
- Engine S6/S9: traceparent adoption, evidence after queue publication, terminal status from
  `Terminated` (`adapters/inprocess.py`, `adapters/queue_runner.py`, `run_evidence.py`,
  `runner/main.py`; `test_run_evidence_lines.py`).
- SDK: foreign-DB refusal, truthful effective-config reporting, complete recorded prompts,
  report-backed golden authority; never weaken replay fixtures to hide D2 changes
  (`tests/e2e/test_fresh_dump_contracts.py`, `test_correlation_chain.py`, `slice_snapshot.py:603-608`).
- Preserve prior tests through the compatibility window; at an intentional contract retirement
  record the approved old-to-new assertion mapping; never delete, weaken or skip unrelated coverage.

## 4. Gates and how they close

| Gate | Closes when |
| --- | --- |
| G1 (first units) | owner approves Stage 0 + A1 scope in plain words and re-approves the D7 ordering; U0/U0e/U1 exist in Linear before code |
| G2a/b/c | each A-stage's acceptance in §3 met; consumer lanes run explicitly; no OpenAPI change before A4 |
| D15, D17 → G3 | successor route shape and hosted mutability rule decided; U4/U4e filed |
| D11, D14, Q01–Q04 → G4 | backing chosen; dual-write owner decided and tested; versions, census and key access authorised; writer fencing in place; fixture swap of the 18 feature suites, the facade-suite split and the bootstrap re-target planned; public wording follows D20 even if backing mechanics choose an internal aggregate |
| D16 → G5a | defaults source during the transition decided; impact plan approved; rehearsed rollback includes the defaults mode |
| D4 date, D12 → G5b | sunset date; selector semantics after cutover; provenance census; accepted-work disposition; worker env audit |
| D6 → G6 | retention fulfilled; reference-safe cleanup proven; deletion approved |
| D13, M0 | catalog write/version handling resolved; successor protocols decided for `X-Profile` removal; only then `--write` |
| D18 | admin successor timing and shape (may wait for D11) |

Implementation details inside an approved contract belong to the agent. Escalate material new
blockers as one grouped report with recommendations and continue independent authorised work.

### Branch, checkout and catalog notes

The code branch started from `17048f5d` and must never gain catalog-only commits as ancestors or
payload; Stage 0 and A1 are committed with explicit path staging, while the `solutions/` overlay
remains untracked and excluded. The catalog now lives in `screamingface-design` (`679aa8f`, PR #18);
the app-repo overlay holds only the generator tooling.
Read-only catalog checks may run; no `--write`, no regeneration and no version reset before M0.
No push, PR, staging or commit is authorised by this plan. Local `main` and the OME-1178 branch
retain catalog-only history; do not merge, cherry-pick or push them.

## 5. Commands (from the repo root)

```sh
# aigateway gates
uv run --project apps/aigateway .claude/scripts/run_gates.py aigateway
# PostgreSQL-marked tests (testcontainers)
(cd apps/aigateway && uv run pytest -m needs_postgres -q)
# consumer lanes (run explicitly; CI path filters skip them for a gateway-only diff)
uv run --project apps/screamingface-engine .claude/scripts/run_gates.py screamingface-engine
uv run --project packages/screamingface .claude/scripts/run_gates.py screamingface
uv run --project packages/url4 .claude/scripts/run_gates.py url4
(cd apps/aigateway-ui && npm run lint && npm run typecheck && npm run test:ci)
# catalog checks (read-only; overlay tooling in the app checkout, catalog in screamingface-design)
PY=apps/aigateway/.venv/bin/python
"$PY" -B solutions/_tools/export_contracts.py
"$PY" -B solutions/_tools/project_models.py --check
"$PY" -B solutions/_tools/check_coverage.py --check
"$PY" -I -B -m unittest discover -s solutions/_tools -p 'test_*.py' -q
NEXT_TELEMETRY_DISABLED=1 npx --yes @bershadsky/metaframework@0.5.1 check --dir ./solutions
```

`screamingface-e2e-replay.yml` runs on `apps/aigateway/**` changes and pins 404
`profile_not_found`; A1–A4 keep it green, and a Stage D code rename updates it in the same PR.
