---
ticket: OME-1245
stack: screamingface-engine
status: in_progress   # gates green 2026-09-21; commit/PR await owner authorization
started: 2026-09-21
finished:
---

# OME-1245 — Move the Hosted Engine listing onto the availability successor

## Intent

Stage A4 of `OME-1138`, Engine half (plan unit U4e). The Hosted Engine's `/v1/connections`
listing still aggregates the gateway's legacy `GET /v1/auth/profiles` body locally through
`connections/profile_availability.py`, which ties the Engine to Profile vocabulary the later
backing switch removes. `OME-1244` (merged as `2da45896`) published the caller-scoped successor
`GET /v1/provider-access` (D17: rows of `provider` and `status` only, `Cache-Control: private,
no-store`, inbound `X-Profile` non-selecting). This unit makes the Hosted branch read that one
listing after the provider catalogue, drops the local Profile decoder, does not forward
`X-Profile` on the availability request, and replaces the internal `listing_source` switch with
the D15 explicit mutability rule: Hosted `mutable=False`, Local `mutable=True`, every Hosted
mutation refused before any network or storage I/O. The Engine `/v1/connections` DTO field set
and the Local Engine `/v1/oauth/connections*` behaviour stay unchanged, so the SDK strict decoder
needs no change.

Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.5, §4 (Hosted Engine row),
§5 A4, §8 (D15, D17), §11. Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md` §2 U4e,
§3 A4. Design: catalog `protocol/provider-access-availability` v1 ("The Hosted Engine Consumer"
section names this switch as the accepted A4 target) and `product/engine` v3 ("Provider
availability, by mode"), both on design `main` since PR #22 — the metamodel gate is satisfied,
no design change is needed for this unit.

## Decisions

- **F-A4-1 (owner, 2026-09-21, recorded on the issue):** the prior suite
  `tests/unit/test_connections_profile_availability.py` pins `listing_source="profiles"` and the
  local `/v1/auth/profiles` aggregation, which this unit removes by design. It is re-expressed at
  the successor seam as `tests/unit/test_connections_provider_access_availability.py`;
  `listing_source="profiles"` is not kept alive. Every prior expectation is carried over: caller
  scoping, secret-freedom, per-fixture status equality, disabled-provider rows ignored, malformed
  body rejected, builder selection, additive fields tolerated, mutation refusal before I/O, and
  the required keyword at the composition seam. This is the only prior-test change in the unit.
- **One flag, both jobs (D15):** `listing_source` already decided both which gateway listing
  feeds `list()` and whether mutations are refused. `mutable: bool` names that coupling: an
  adapter that cannot mutate the state it reports (Hosted) reads the read-only availability
  successor; an adapter that manages its own managed rows (Local) reads `/v1/oauth/connections`.
  The adapter keeps `mutable=True` as its default so every existing Local/default-path suite
  stays green unmodified; `build_connections` requires the keyword, as `listing_source` was.
- **`X-Profile` omission without a header-assembly fork:** the availability request is issued
  for `dataclasses.replace(caller, profile=None)`, so `_headers` and its OME-1119 last-writer
  invariant stay untouched and `/v1/providers` keeps forwarding the header exactly as today.
- **Decoder placement:** the successor decoder lives in its own module
  `connections/provider_access_availability.py` (the issue and hints forbid growing the already
  oversized `aigateway.py`); it is strict in the same way the Profile decoder was (`providers`
  must be a list of objects with a valid provider id and a status from the `ConnectionStatus`
  family; a duplicate provider row is malformed because it would force a guessed status), and
  tolerant of additive envelope/row fields, which it never exposes.
- **`profile_availability.py` deleted:** call-site inspection over `src` and `tests` shows
  `AigatewayConnections._profile_statuses` as the only production caller and the re-expressed suite
  as the only test caller.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/connections/aigateway.py` — replace
  `listing_source: ListingSource` with `mutable: bool`; Hosted branch of `list()` reads
  `GET /v1/provider-access` (no `X-Profile`) through the new decoder; remove `_PROFILES_PATH`,
  `_profile_statuses`, `_profile_connection`, `ListingSource`; `_require_mutable` tests
  `not self._mutable`; file shrinks.
- `apps/screamingface-engine/src/screamingface_engine/connections/provider_access_availability.py`
  — new strict decoder `decode_provider_access(body) -> dict[str, ConnectionStatus]`.
- `apps/screamingface-engine/src/screamingface_engine/connections/profile_availability.py` —
  deleted.
- `apps/screamingface-engine/src/screamingface_engine/connections/__init__.py` —
  `build_connections(settings, *, mutable: bool, client_factory=...)`; drop `ListingSource`.
- `apps/screamingface-engine/src/screamingface_engine/app.py` — Hosted composition
  `build_connections(settings, mutable=False)`.
- `apps/screamingface-engine/src/screamingface_engine/local.py` — Local composition
  `build_connections(settings, mutable=True)`.
- `apps/screamingface-engine/tests/unit/test_connections_profile_availability.py` → re-expressed
  as `tests/unit/test_connections_provider_access_availability.py` (F-A4-1).
- `docs/tasks/2026-09-21-OME-1245-hosted-engine-availability-successor.md` — mirror
  (status, log).
- No dependency change; no gateway change; no SDK change.

## Test plan

RED first, all in `tests/unit/test_connections_provider_access_availability.py`:

- Hosted listing (`mutable=False`) requests `/v1/providers` then `/v1/provider-access`, is caller
  scoped, and exposes neither `auth_method` nor `account_label`; the legacy `/v1/auth/profiles`
  path is never requested.
- With `Caller(..., profile="team", traceparent=...)`, the availability request carries identity
  and `traceparent` but no `X-Profile`, while `/v1/providers` still carries it (unchanged).
- Per-fixture equality: each status the gateway may publish (`connected`, `pending`, `error`,
  `needs_reauth`, `not_connected`) maps onto the catalogue row unchanged; a provider the listing
  omits is `not_connected` — the same user-visible answers the prior fixtures produced.
- Availability rows for providers outside the catalogue create no rows.
- Malformed availability body (`providers` missing / not a list / non-object row / invalid
  provider id / legacy state vocabulary / missing status / duplicate provider / non-JSON body)
  → `ConnectionBadResponse` (502); an upstream 503 on the availability request keeps the
  existing `ConnectionUnavailable` mapping.
- `build_connections(..., mutable=False)` selects the Hosted listing.
- Additive envelope and row fields are tolerated and never surface.
- Hosted `connect` / `start_oauth` / `disconnect` raise `ConnectionMethodUnsupported` (400) with
  no gateway request and without echoing the credential.
- `mutable` is a required keyword of `build_connections`; `listing_source` is gone.
- Local listing with explicit `mutable=True` still reads `/v1/oauth/connections`, never
  `/v1/provider-access`, and its mutations still reach the gateway.
- `/v1/connections` DTO field set pinned (`ConnectionResponse` and `Connection`).

## Acceptance

- Hosted listing uses `GET /v1/provider-access`; no `/v1/auth/profiles` aggregation; decoder
  module deleted.
- Per-fixture equality with today's Hosted aggregation.
- `X-Profile` not forwarded on the availability request.
- Hosted mutations refused before any gateway request or storage I/O.
- Local Engine behaviour unchanged; every prior suite other than the re-expressed one untouched
  and green.
- Engine `/v1/connections` DTO field set unchanged; SDK untouched.
- Engine gates green: `ruff check`, `ruff format --check`, `pyright`, layering gate, full suite
  with coverage ≥ 80%; `run_gates.py screamingface-engine --base 2da45896`.
- `screamingface-e2e-replay` owned by CI on the PR (it pins legacy `profile_not_found`, which this
  unit does not touch).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus one additive test appended to
  `apps/screamingface-engine/tests/unit/test_local_aigateway_connection.py`
  (`test_local_app_wires_a_mutable_adapter`, pins the Local root at `mutable=True`).
  Source: `connections/aigateway.py` 473 → 471 lines (net −2; `_PROFILES_PATH`, `ListingSource`,
  `_profile_statuses`, `_profile_connection` gone; `_availability`, `_status_only` added;
  `_disconnected` now delegates to `_status_only`); `connections/provider_access_availability.py`
  new (47 lines); `connections/profile_availability.py` deleted (40 lines); `connections/__init__.py`
  requires `mutable`; `app.py` passes `mutable=False`; `local.py` passes `mutable=True`. Tests:
  `tests/unit/test_connections_profile_availability.py` deleted and re-expressed as
  `tests/unit/test_connections_provider_access_availability.py` (359 lines, 28 test items).
  Whole `src` diff: 46 insertions, 84 deletions. No dependency change; no gateway, SDK or public
  DTO change.
- **Commits:** none yet — staging, commit, push and PR await owner authorization. Proposed
  subject `feat(screamingface-engine): read provider-access availability for hosted listings`,
  body `Refs: OME-1245`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base 2da45896
  --skip-append-only` → **ALL GATES GREEN** (`ruff check` ✓, `ruff format --check` ✓, `pyright`
  0 errors ✓, `check_layering.py` "LAYERING OK" ✓, `pytest --cov … --cov-fail-under=80` ✓).
  Separate coverage run from `apps/screamingface-engine`: **3283 passed, 16 skipped, 93.54%**
  (floor 80%). Append-only check run on its own against `2da45896`: red for exactly one path,
  `D tests/unit/test_connections_profile_availability.py` — the F-A4-1 re-expression — and
  nothing else, which is why the runner was invoked with `--skip-append-only`. RED confirmed
  before implementation (28 failed / 8 passed: every new test failed on the missing `mutable`
  keyword). Focused connection suites after GREEN: 96 passed. Metamodel gate: satisfied by design
  `main` after PR #22 (verified against `origin/main`, not a local design checkout).
  `screamingface-e2e-replay` and the Python 3.12 leg are CI-owned on the PR; this unit touches
  no path that lane pins (`profile_not_found` untouched). SDK suites untouched — no path under
  `packages/screamingface` changed, so the path-filtered SDK lane does not run and nothing there
  moved.
- **Deviations:**
  - The one prior-test change is the deletion of `test_connections_profile_availability.py`,
    re-expressed at the successor seam per the owner's F-A4-1 decision; every expectation of that
    suite is carried over (see Test plan) and the legacy listing is asserted never requested.
    Recorded here because the append-only gate had to be skipped for that path alone.
  - One test appended to a prior file (`test_local_aigateway_connection.py`); additive only.
  - The Hosted composition root `create_app_from_env` is excluded from coverage by the repo's
    INFRA rule, so its `mutable=False` wiring is pinned at the `build_connections` seam and by
    the reviewed diff rather than by a test — the same coverage level the prior suite had.
  - The adapter keeps `mutable=True` as its constructor default so every default-path suite
    (`test_connections_aigateway.py`, `test_profile_env_characterisation.py`) stays green
    unmodified; the composition seam is where the flag is required (D15).
  - The catalogue call (`/v1/providers`) still forwards `X-Profile`, as today; the new suite pins
    the omission on the availability request only. Carrier retirement stays Stage D.
- **Wisdom review:** no simpler design found — one flag now carries the coupling the old switch
  hid; no speculative generality (no shim keeps both Hosted paths alive); the duplicated
  `Connection(...)` construction between `_disconnected` and the old `_profile_connection` is
  gone. Tests assert behaviour and the named invariants (caller scoping, secret-freedom, refusal
  before I/O, per-fixture equality, DTO field set). Blast radius: internal adapter API
  (`build_connections` keyword) and two composition roots; no public contract, schema or
  dependency touched. Security: no credential can leave a Hosted Engine (refusal precedes I/O);
  a malformed body fails closed as 502; no secret logged. No `# type: ignore`; no bare `except`.
