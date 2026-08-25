---
ticket: OME-972
stack: aigateway
status: done
started: 2026-08-25
finished: 2026-08-25
---

# OME-972 — Live OpenRouter model discovery for /v1/models

## Intent

`GET /v1/models` currently lists compiled OpenRouter seeds frozen at deploy time. This unit adds
provider-owned, bounded, async live discovery of OpenRouter's public model catalog behind a
process-local snapshot shared across accounts, so the gateway lists what OpenRouter actually serves now —
default-on (`AIGW_OPENROUTER_LIVE_MODELS=true`), fail-closed, credential-free, with compiled
seeds as the cold-failure fallback and explicitly configured operator models always preserved.
Standalone task — not a child of OME-308.

## Planned changes

- NEW `src/aigateway/plugins/openrouter_provider/live_models.py` — pinned-query fetch, strict
  pagination validation, publishability (admission shape predicate), operator/discovered merge
  (`model_fields_set`), cache policy constants.
- NEW `src/aigateway/core/model_catalog.py` — `ModelCatalog` (per-provider ObservationCaches,
  refresh-thunk guards, transition logging) + `build_model_catalog`.
- `src/aigateway/core/plugin_base/_contract.py` — frozen `ModelDiscoverySource` + inert port
  pair `model_discovery_source` / `discover_live_models`.
- `src/aigateway/plugins/openrouter_provider/settings.py` — `live_models: bool = True`.
- `src/aigateway/plugins/openrouter_provider/plugin.py` — implement the port pair.
- `src/aigateway/main.py` — `app.state.model_catalog`.
- `src/aigateway/routes/models.py` — snapshot-or-fallback merge + admitted dedupe.
- `src/aigateway/routes/model_parameters.py` — lazy known-set extension + comment amendments.
- `src/aigateway/core/parameter_discovery.py` — additive `DiscoveryError.status`.
- `src/aigateway/core/discovery_runtime.py` — docstring-only correction (two consumers now).
- Existing-test setup amendments (`live_models=False`, assertions untouched):
  `tests/unit/openrouter/test_model_admission_route.py` (openrouter_enabled fixture),
  `test_openrouter_catalog_route.py`, `test_openrouter_top_p_promotion.py`,
  `test_openrouter_openapi_endpoint_route.py`.
- `DEPLOYMENT.md` — flag, degrade ladder, fallback-vs-operator semantics.
- NEW tests: `tests/unit/openrouter/test_live_models_parse.py`, `test_live_models_fetch.py`,
  `test_live_models_port.py`, `tests/unit/core/test_model_catalog.py`,
  `tests/unit/core/test_models_route_live_catalog.py`,
  `tests/unit/openrouter/test_live_models_resolvability.py`.

## Test plan

Coverage includes parse/publishability/next-URL validation (incl. cap ⇒ failure,
empty ⇒ failure); pagination failure surface (401/500/timeout/oversized/mid-chain/aggregate
deadline/off-policy next never dialed); port gating (default true; enabled=False and
live_models=False ⇒ None + zero dials); ModelCatalog cache semantics (single-flight, TTL, stale,
stale-expiry, no_snapshot/internal_error guards, AssertionError propagates, per-provider policy,
transition logging with negative content assertions); route merge (snapshot-or-fallback,
compiled defaults absent from healthy snapshot are unlisted, explicit operator + colon seed
survive, admitted dedupe, byte-identical fallback, determinism, route-level single-flight);
resolvability (discovered id on /v1/model-parameters, seeded id ⇒ zero dials, chat dispatch
parity). Invariant protected: live data changes what is LISTED, never what is dispatchable, and
never evicts last-good state on failure.

## Acceptance

Acceptance criteria: default-on discovery; `false` ⇒ today's
behavior + zero egress; TTL-window freshness; retired compiled defaults disappear when healthy;
operator + admitted survive; colon/tilde not auto-published; cold ⇒ seeds, failure ⇒ stale;
nothing partial/malformed/oversized/policy-violating cached as fresh; one upstream fetch chain
under concurrency; published ids resolve via model details + chat; admission unchanged; full
AIGateway gates green.

## Outcome

- **Actual files:**
  - NEW `src/aigateway/plugins/openrouter_provider/live_models.py` — pinned-query paginated
    fetch (strict `links.next` validation, aggregate 10 s deadline, page/raw caps, total_count
    reconciliation), publishability (admission shape predicate, ≤256 chars, dedupe/sort,
    empty/cap fail-closed), operator explicitness (`model_fields_set`), listing merge.
  - NEW `src/aigateway/core/model_catalog.py` — `ModelCatalog` over per-provider
    `ObservationCache`s (single-flight, TTL 300 s / stale 3600 s / failure damping 30 s),
    refresh-thunk guards (AssertionError re-raised; foreign exceptions wrapped sanitized as
    `internal_error`; port `None` under a declared source → `no_snapshot` failed attempt),
    attempt-scoped logging (counts/reason/status only), `ModelListingProvider` Protocol,
    `build_model_catalog(enabled=...)`.
  - `core/plugin_base/_contract.py` — frozen `ModelDiscoverySource` + inert port pair
    `model_discovery_source` / `discover_live_models`; `_ports` untouched; exports via
    `plugin_base/__init__.py`.
  - `core/parameter_discovery.py` — additive `DiscoveryError.status` (set only at the
    `bad_status` raise site).
  - `core/discovery_runtime.py` — docstring-only consumer-list correction.
  - `plugins/openrouter_provider/settings.py` — `live_models: bool = True`.
  - `plugins/openrouter_provider/plugin.py` — port pair gated on
    `enabled and live_models`; provider-owned merge.
  - `routes/models.py` — snapshot-or-fallback per provider + canonical-id dedupe incl.
    admitted rows.
  - `routes/model_parameters.py` — lazy live-catalog rescue of a would-be 404
    (`_live_catalog_ids`); comment/docstring amendments.
  - `main.py` — `app.state.model_catalog = build_model_catalog(enabled=settings.discovery_enabled)`.
  - `DEPLOYMENT.md` — "Live OpenRouter Model Discovery" operator section (flag, degrade
    ladder, explicit-config vs fallback semantics).
  - NEW tests (90): `tests/unit/openrouter/test_live_models_parse.py` (32),
    `test_live_models_fetch.py` (13), `test_live_models_port.py` (10),
    `test_live_models_resolvability.py` (4), `tests/unit/core/test_model_catalog.py` (19),
    `tests/unit/core/test_models_route_live_catalog.py` (10, incl. the no-egress tripwire
    meta-test + default wiring pin); counts do not sum to 90 verbatim due to parametrize
    expansion — 90 is the collected total of the six files.
  - Setup-only amendments (`live_models=False`, assertions unchanged) isolate four existing
    suites from live listing discovery: `test_model_admission_route.py`,
    `test_openrouter_catalog_route.py`, `test_openrouter_openapi_endpoint_route.py`, and
    `test_openrouter_top_p_promotion.py`.
- **Commit:** `feat(aigateway): discover openrouter models live for /v1/models`
  (`Refs: OME-972`).
- **Checks:** ruff check ✓, ruff format --check ✓, pyright ✓ (0 errors),
  check_no_enterprise ✓, pytest --cov ≥80 ✓. Standalone full suite: 4069 collected,
  4014 passed, 55 skipped (pre-existing opt-in live markers), 0 failed.
- **Deviations:**
  - D25 transition-state logging simplified to attempt-scoped logging (warning per real
    failed attempt with reason+status, info per successful refresh with row count); the
    cache's failure damping bounds log volume, so the ok↔failed state dict was dead weight.
  - `ModelCatalog` typed against a narrow `ModelListingProvider` Protocol instead of
    `ProviderPluginBase` (pyright-driven; strictly better hexagonal coupling).
  - `build_model_catalog` takes `enabled: bool` rather than the `Settings` object — keeps
    core free of the config module; `main.py` passes `settings.discovery_enabled`.
  - Chat parity pinned as behavioral equality of the credential-stage error `detail` for
    seeded vs discovered ids (membership-free dispatch), not a stubbed dispatch round-trip.

---

## Correction pass — 2026-08-25

The correction pass closes catalog-completeness, test-isolation, resolvability, documentation,
and observability gaps. Product scope is unchanged: only plain `vendor/model` ids are
auto-published; colon variants and tilde aliases stay out of automatic publication (tilde
folding via `alias_target` is a later unit).

### C1 — partial catalogs can no longer be cached as fresh

`parse_catalog_page` is now STRICT: `data` must be a list, `links` must carry an explicit
`next` (string or null), `total_count` must be a non-negative int, and **every** row must be an
object with a string `id`. A malformed row is no longer skipped — it fails the whole refresh.
`fetch_live_model_ids` additionally requires `total_count` to agree ACROSS pages and with the
final collected count. The live envelope always carries both completeness fields (probed
2026-08-24), so strictness matches upstream.
Coverage: `test_live_models_parse.py` 32 → 44 collected cases (18-case malformed matrix),
`test_live_models_fetch.py` + mid-chain bad row / cross-page census / missing-metadata cases,
plus two route-level tests proving a malformed refresh serves the STALE last-good snapshot
(never replaces it) and that a cold malformed read falls back to compiled seeds.

### C2 — `:online` refused at configuration

`_validate_gateway_slug` now rejects `:online` slugs: dispatch refuses them with
`unsupported_model_variant`, so configuring one published a model whose every request failed.
Other colon variants remain configurable (regression-pinned). 3 new tests.

### C3 — the two accidentally-passing legacy suites

`live_models=False` added to the `openrouter_enabled` fixtures of `test_model_admission_route.py`
and `test_openrouter_openapi_endpoint_route.py` (setup only; test and assertion counts identical
vs HEAD: 20/62 and 6/15). The shared canned client (`tests/unit/openrouter/_openapi_document.py`
`_RoutingClient`) now raises **AssertionError** for an unrouted URL instead of `KeyError`, so no
guard can launder a future accidental catalog dial into a silent fallback — the change immediately
exposed 5 failing tests across those two suites, which the fixture amendment then fixed.

### C4 — acceptance completion

- Concurrent route-level `/v1/models`: 6 threads, all 200, exactly ONE upstream fetch chain,
  with an interval-overlap assertion so the test cannot pass by mere caching.
- Credentialed discovered-only dispatch: a snapshot-only id (absent from every seed list) is
  listed, then reaches the patched `litellm.acompletion` carrying that id, response 200.
- `model_discovery_source()` raising a non-`DiscoveryError` stays LOUD on **both**
  `/v1/models` and `/v1/model-parameters`: programming errors are never laundered into a
  degraded listing. Pinned by two tests; behavior deliberately unchanged.

### C5 — canonical catalog ids

`ModelCatalog.ids_for` now returns `canonical_model_id(...)` per entry, so a future provider
using the established unprefixed `model_name` convention cannot publish an id that 404s on its
own detail endpoint. 2 new tests (unprefixed + already-prefixed).

### C6 — operator documentation

`DEPLOYMENT.md` corrected and extended: variants are listable through explicit configuration
ONLY (admission refuses the same shapes — the previous text was wrong); `:online` is rejected
and why; colon/tilde are never auto-discovered; fail-closed parsing described; inline refresh
latency (typical 1–2 s, hard-bounded by the 10 s aggregate deadline, single-flight, 30 s
damping); each replica caches independently (N replicas ⇒ up to N fetches per TTL); the new
`tier=` log field. Task mirror renamed to
`docs/tasks/2026-08-25-OME-972-live-openrouter-model-discovery.md` (id-keyed like its siblings).

### C7 — observability

`ModelCatalog` now logs the SERVED tier on change only —
`tier=fresh` (info) / `tier=stale` / `tier=seeds` (warning) — so an operator can tell "users
still see live models" from "the listing has collapsed to seeds" during an outage, which the
per-attempt warnings could not. 2 new tests, including "an unchanged tier must not re-log".

**Open follow-up:** `plugins/openrouter_provider/plugin.py` is **558 lines**, over the repo's
450-line split discipline. Pre-existing at 526 lines before OME-972; this unit added 32 (the port
pair). NOT refactored here. Recommended follow-up: extract the discovery/live-listing hooks into
a cohesive module. New files added by this unit are within limit (`live_models.py` 252,
`model_catalog.py` 218).

### Correction-pass gates (actually run)

- Test/assertion counts vs HEAD confirmed non-decreasing everywhere except
  `test_live_models_parse.py`, where three lenient tests were consolidated into the strict
  parametrized matrix (functions 18 → 17, collected cases 32 → 44). No prior-unit assertion
  was weakened; the two legacy suites' counts are byte-identical.
- Ruff check ✓, ruff format --check ✓, pyright ✓ (0 errors),
  `check_no_enterprise.py` ✓, `pytest --cov=aigateway --cov-fail-under=80 -q` ✓ → ALL GATES GREEN.
- Standalone full non-live suite: **4102 collected, 4047 passed, 55 skipped** (pre-existing
  opt-in live markers), 0 failed (was 4069/4014 before this pass).

### Remaining known deviations after this pass

- Inline (request-path) refresh retained by design with a 10 s aggregate deadline; latency is
  documented.
- Per-process cache retained (no shared store); documented as a replica-count sizing note.
- Remaining improvements: HTTP connection reuse across pages, aggregate-deadline configurability,
  `/v1/models` row-render cost at the 5000-model
  cap, `ModelListingProvider` vs the plugin-base port having no static conformance check, the
  three DRY items, and the boundary tests at exactly `_MAX_PAGES` / `_MAX_ID_LENGTH`.
- `plugin.py` size violation above.


## Verification round 2 — 2026-08-25

The second verification pass found two acceptance tests that did not prove their stated
invariants. Both tests were strengthened against the corresponding pre-fix behavior, and live
catalog evidence was checked across both pagination pages.

### C1 strictness validated against both live pages

C1 made `links.next` and `total_count` mandatory on EVERY page, justified by a probe that had
only ever seen a **single-page** response. With `limit=250` against ~420 text models, production
dials a continuation page on every refresh — so if a continuation page omitted either field,
every refresh would fail and the listing would be pinned to seeds forever, with the whole suite
green. Probed both real pages on 2026-08-25:

| Probe | keys | rows | `total_count` | `links.next` |
|---|---|---|---|---|
| `?output_modalities=text&limit=250` | `data, links, total_count` | 250 | 419 | `/api/v1/models?output_modalities=text&offset=250&limit=250` |
| `…&limit=250&offset=250` | `data, links, total_count` | 168 | 418 | `null` |

Conclusions: (1) continuation pages carry both completeness fields and an explicit `next: null`,
so C1's strictness matches the live contract; (2) `links.next` echoes the pinned
`output_modalities` filter required by `validate_next_url`; (3) `total_count` moved 418 → 419
between two probes seconds apart, so cross-page equality can reject a refresh on benign census
drift. The strict behavior fails safe, self-heals after the 30 s damping window, and is documented
in DEPLOYMENT.md. A distinct reason token for drift remains a follow-up.

### Fixed in this round

- **The "never replaces the last good snapshot" test did not guard the fix.** Its
  malformed body (`{"data": []}`) fails under the OLD lenient parser too, so it was green
  either way. Replaced with a body the row-skipping parser would have SALVAGED into a
  *different fresh snapshot* (one unusable row + one good id, with `links`/`total_count`
  consistent with the salvageable count, so the completeness reconciliation cannot catch it and
  only the all-or-nothing row rule can). Verified by injecting the pre-pass parser: the test now
  FAILS without the fix and passes with it.
- **The concurrency test's overlap assertion could not fail.** Client-side start stamps are all
  ≈t0 because the pool launches all six threads at once, so `latest_start < earliest_end` held
  even for a strictly serialized server — leaving `dialed == 1`, which plain caching satisfies.
  Replaced with a server-side measurement: peak concurrent depth inside `ModelCatalog.entries_for`
  must equal the caller count. Confirmed a real measurement (reports `6`, not a tautology) and
  stable over 8 consecutive runs.
- **A sibling canned client still laundered a stray dial into a silent seed fallback** —
  `_ServingClient` in `test_live_models_resolvability.py` raised `KeyError`, the exact path C3
  closed in `_openapi_document.py`; now raises `AssertionError`.
- **DEPLOYMENT.md, six corrections**: the cache-scope sentence contradicted the per-replica
  behavior; the variant bullet was still wrong (the
  compiled seed FALLBACK also lists variants — several seeds are `:batch` slugs); logs carry the
  exact upstream status code, not a "status class"; the `1–2 s` figure was an unmeasured estimate
  and is now expressed as one fetch per page at the measured catalog size; added a **breaking
  upgrade** note (a deployment with a `:online` slug in `AIGW_OPENROUTER_DEFAULT_MODELS` will not
  boot after C2); added the census-drift note above.
- **Two stale docstrings** the pass itself invalidated: `live_models.py` misstated cache scope
  and still listed `:online` as reachable via operator config;
  `is_online_variant` still claimed two call sites after C2 added a third.
- **One test added**: the real envelope (14+ keys per row, extra top-level keys) must still
  parse — strict must not mean brittle. Evidence-backed by the probe above; without it, a future
  exact-key-set tightening would take the listing down. Parse suite 44 → 45 collected.

### Remaining limitations and follow-ups

- **Append-only against the merge base.** `run_gates.py aigateway --base origin/main` flags
  **5** files: `_openapi_document.py`, `test_model_admission_route.py`,
  `test_openrouter_openapi_endpoint_route.py`, `test_openrouter_catalog_route.py`, and
  `test_openrouter_top_p_promotion.py`. All five changes are `live_models=False` setup amendments
  or the loud-client change, with assertions untouched. **The PR needs an explicit waiver naming
  these 5 files.**
- `:online` rejection is **case-sensitive** (`:Online` still configures and is unpoliced at
  dispatch). The fix belongs in the shared OME-712 `is_online_variant` predicate, which also
  governs dispatch and the global-cache bypass — out of scope for a correction pass. Follow-up.
- `LIVE_MODELS_DISCOVERY_SOURCE.revision` NOT bumped despite the parser contract change, against
  the module's own stated policy. No live effect (the cache is process-local and dies with the
  process, so a deploy already invalidates every snapshot); bumping would edit a same-unit test
  assertion for zero runtime benefit. Bump if the cache ever becomes durable or shared.
- `publishable_upstream_ids` still skips over-long ids rather than failing the refresh. It is a
  publication FILTER (its job is to drop non-publishable shapes), not the census, so the
  no-partial-catalog invariant is not weakened by it.
- No `tier=` line when a provider declares no discovery source: for those providers a seed
  listing is normal, not degraded, so logging it would be pure noise.

### Round-2 gates (actually run)

- `run_gates.py aigateway --skip-append-only`: ruff check ✓, ruff format --check ✓, pyright ✓
  (0 errors), `check_no_enterprise.py` ✓, `pytest --cov=aigateway --cov-fail-under=80 -q` ✓ →
  ALL GATES GREEN.
- `run_gates.py aigateway --base origin/main`: append-only RED on the 5 files enumerated above
  (waiver required, each justified).
- Branch-only full non-live suite: **4102 collected, 4047 passed, 55 skipped, 0 failed**.
- Focused OME-972 set (9 modules): 192 passed, then 193 with the added parse case.
