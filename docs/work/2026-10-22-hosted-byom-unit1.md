---
ticket: OME-1721
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-22
finished:
---

# hosted-byom-unit1 — remote endpoints: chat catalog, shared cache, approved origins

## Intent

Second slice of hosted bring-your-own-model endpoints in the AI Gateway, on top of Unit 0
(`ca31b88ef`, `bdf5746a4`, OME-1712). It turns the compatibility proof into the common chat
plumbing: approved HTTP, IP and port origins besides HTTPS with DNS on 443; a catalog and model
details filtered by the static account grants, with the remaining metadata, admission and
availability surfaces closed to ungranted accounts; the shared response cache for the eligible
chat subset through the existing pure projection contract, with and without `max_tokens`; and a
bounded, reused HTTP client. Engine, classification, UI, Helm, hot reload, Taxonomy, a custom
DNS or private-address guard and local NATS stay out of scope. Decisions come from the
owner-held planning pack, kept local by the owner's instruction (not copied into
`docs/spec`/`docs/plan`). One PR for the whole unit, by the owner's choice.

Owner decisions (2026-10-22):

- The cache projection is body-only. Origin, request path and upstream model never enter key
  material. A canonical model ID is an immutable semantic binding; retargeting needs a new
  identity, and allowing a retarget of an old ID would be a separate cache-contract change.
  A cache hit does not check a changed definition. The live path keeps the origin-bound key
  check, so a key validated on an old origin is never sent to a new one. A new upstream model
  under the same alias still breaks the immutable-identity contract.
- `enabled = false` is the operator kill switch: `participates_in_global_cache` returns False,
  and a miss or bypass is still refused before upstream I/O. The hook ignores account grants and
  key state; projection and keys do not depend on `enabled`.
- Origins: HTTP and HTTPS; FQDN and single-label DNS names, including Docker service names;
  canonical IPv4; IPv6 in brackets; private and loopback addresses; ports 1 to 65535.
- Prior-test edits are shown to the owner before any production code changes. Approved as
  shown: `test_definitions` drops the five now-valid origins from its refusal list and is renamed
  `test_non_canonical_origins_are_refused`; `test_reader` uses `ftp://` for its invalid origin;
  `test_plugin` expects the declared model entry; `test_app_regressions` compares the bundled
  providers' rows only. Pinned in a test-change approval file once the issue is filed.
- The participation hook requires both: the endpoint is enabled, and the requested alias is a
  declared chat target of this provider. A removed alias's rows are never served. It still reads
  no grant and no key.
- Still refused as origins: unspecified addresses (`0.0.0.0`, `::`), as unsuitable destinations;
  IPv4-mapped IPv6 in any spelling, hexadecimal included, checked on the parsed address, as a
  chosen format limit of the prototype rather than a claim that it names no host; an IPv6 zone,
  which httpx keeps percent-encoded in the host and so would not reach the intended interface.
  Link-local addresses stay allowed while only the operator writes the config.
- A future UI does not change this trust model by itself: while a user only proposes an origin
  and the operator reviews and approves it before activation, approval stays manual. A stronger
  address guard becomes necessary when untrusted addresses are accepted automatically, or when
  network isolation is a separate requirement.

## Planned changes

- `plugins/remote_endpoint/definitions.py`: the origin rules above; the default port per scheme
  is dropped, so equal origins compare equal in the credential blob.
- `core/endpoint_access.py` and `plugins/remote_endpoint/policy.py`: a `VIEW` operation.
- `plugins/remote_endpoint/plugin.py`: `register_models()` returns the declared chat targets;
  `global_cache_projection`, `participates_in_global_cache` and
  `cache_reference_from_cached_response`; the endpoint's `enabled` flag from composition.
- New `plugins/remote_endpoint/global_cache.py`: the body-only projection.
- `plugins/remote_endpoint/request.py`: `max_tokens` keyed instead of bypassed.
- `plugins/remote_endpoint/transport.py`, `provider_composition.py`, `main.py`: one reused HTTP
  client per endpoint, created on first use and closed at application shutdown. Each instance
  owns its client; `close_remote_endpoints(registry)` in the composition module closes them, so
  `compose_providers` keeps returning the access policy and `test_composition` stays unchanged.
  The pool is bounded at httpx's own default (100 connections, 20 kept alive); core admission
  still caps concurrent calls per provider first (4 by default).
- Routes `models`, `providers`, `model_parameters`, `model_admission`,
  `provider_access_availability`, `oauth_connections`: a `VIEW` check before a remote endpoint is
  listed, described or admitted, answering as each route answers an unknown provider; the two
  listings become `private, no-store` with `Vary: Authorization`.

## Test plan

- Origins: every newly accepted form, canonical comparison (`http://h` equals `http://h:80`),
  refused forms (`0.0.0.0`, `::`, IPv4 inside IPv6, port 0 and 65536, leading-zero IPv4, other
  schemes); an LM Studio-like `http://<ip>:<port>` fake with a real bearer token in readiness and
  dispatch; an HTTPS origin keeps certificate verification on.
- Catalog: a granted account sees its endpoints in `/v1/models`, `/v1/providers` and
  availability and gets the model contract; an ungranted account and a disabled endpoint get the
  route's unknown-provider answer with no upstream I/O; admission never adds a remote endpoint to
  the shared admitted list.
- Cache: account A misses and account B, granted or not, hits with one upstream call; with and
  without `max_tokens`, a changed value changes the key; two endpoints with the same upstream model
  never share a row; a disabled endpoint neither serves nor stores; the projection is pure,
  deterministic and does not mutate the body.
- Cache across config changes, each across a restart on the same stores:
  - participation needs an enabled endpoint and a declared chat alias of this provider;
  - fill the cache, remove the alias: the request bypasses the cache and is refused with no
    upstream call;
  - fill the cache, disable the endpoint: the stored answer is not served and the model is not
    called;
  - enable the same unchanged endpoint again: the stored row is served again;
  - an account without a grant still gets a hit for an enabled, declared target.
- Transport: concurrent calls reuse one client per endpoint; shutdown closes it; a call after
  close is a safe 502.

## Acceptance

- The tests above pass through the real handlers against fake HTTP; Unit 0 tests stay green,
  with only the owner-approved prior-test edits.
- All aigateway card gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `global_cache.py` (new) and five new test files:
  `test_http_origins`, `test_app_catalog`, `test_global_cache`, `test_app_shared_cache`,
  `test_endpoint_client`. Prior tests changed only as approved: `test_definitions`,
  `test_reader`, `test_plugin`, `test_app_regressions`.
- **Commits** (rebased onto `482460344`, 2026-10-27):
  - `1d83d9d13` feat(aigateway): accept approved http and https origins by name or address
  - `50c5fcc46` feat(aigateway): show each configured endpoint only to its granted accounts
  - `0a67e4d4b` feat(aigateway): share cached chats to configured endpoints across accounts
  - `69efb15fa` feat(aigateway): reuse one bounded HTTP client per configured endpoint
  - `d9ae79613` fix(aigateway): share no cookie and close every endpoint client at shutdown
  - `202f40ba6` fix(aigateway): list only registered providers the caller may see
  - `d0c7545e2` fix(aigateway): close every endpoint client even when shutdown is cancelled
  - `61fbae090` fix(aigateway): report the remote endpoint cache revision in every export
- **Gates:** `run_gates.py aigateway --base 482460344` after the rebase: ruff check, ruff format,
  pyright, `check_no_enterprise`, pytest with coverage at least 80% and the append-only check:
  all green; 7355 tests collected, 433 in `tests/unit/remote_endpoint`. After `d0c7545e2` the
  full run is green again with 7359 and 437, and after `61fbae090` with 7363 and 441. The
  first run for `61fbae090` failed once on the login timing test
  `test_unknown_user_timing_close_to_wrong_password`, which compares bcrypt medians by wall
  clock and lies outside this branch; it passed three times alone and in the full rerun. With
  `.claude/test-change-approvals/OME-1721.json` in place the append-only check accepts exactly
  the five approved test transitions. Earlier runs against `fade16614` were green at each part
  (6912 and 426 tests) and after the first review fixes (6920 and 433).
- **Review fixes (2026-10-23),** after an external review of the four feature commits:
  - The shared client kept upstream cookies, so a cookie set on one account's answer rode on the
    next account's request. The client now uses a cookie jar that keeps nothing. A refusing
    cookie policy does not work: httpx copies the jar into a plain one before each request.
  - Shutdown stopped at the first endpoint whose close failed, and a cancelled close could not
    be repeated. Each endpoint now closes on its own and a failure is logged without its text;
    the close runs as one shielded task that a repeat call waits for.
  - `/v1/provider-access` read every stored pair before the route filtered the rows, and still
    listed the pair of a provider no longer registered. By the owner's choice the listing shows
    only registered providers the caller may see: the connection-backed port skips any other
    pair before its Connection or credential state is read, and the route is back to its form
    on main. The stored pair is kept. The Hosted Engine already drops availability rows outside
    the provider catalogue (OME-1245), so its users see no change.
  - One more prior test changed, shown to the owner and approved on 2026-10-23, and pinned in
    the approval file: `test_provider_access_availability_route` checks `pending` on the
    registered `gemini-cli` instead of the unregistered `gemini`, and gains a test that an
    unregistered provider's pair has no row.
  - Open, awaiting the owner: a 401 or a 405 on `/v1/models` and `/v1/providers` is answered
    before the handler and carries no private-cache headers. Its body holds no account data.
- **Second review (2026-10-27),** on the rebased branch: the three fixes above hold.
  - An account without a grant can learn a configured endpoint's ID and alias through the
    shared cache. `GET /v1/cache/entries` lists every account's cached rows with their
    provider, model, stored answer and metadata. With the cache on, a refused chat reports a
    cache `miss` where an unknown provider reports `bypass`, because the lookup runs for every
    account before the grant check. Both match the governing decisions: the product owner
    confirmed in PR #1433 on 2026-10-21 that every gateway cache row, metadata included, is
    community data open to every signed-in account; the hosted BYOM design serves a hit to a
    caller who guessed the model ID, adds no per-account partition, private-cache mode or
    pre-cache grant gate, and keeps the community-cache policy. What is wrong is the wording:
    the Unit 0 and Unit 1 comments promise that a tenant cannot learn which endpoints are
    configured. Open, awaiting the owner's approval of the reworded comments, one of them in a
    prior test file, and of a cache-on refusal test and a cache-listing test.
  - Rows pulled into a local gateway would be served to a local endpoint that reuses a hosted
    ID with another upstream. The design already forbids retargeting a stable ID.
  - The media guard from main (OME-1542) runs before the grant check: a remote image URL sent
    to an ungranted endpoint gets a 422 naming the provider, where an unknown provider gets a
    400. A caller who guesses the ID learns it from the cache status anyway.
  - Fixed in `d0c7545e2`: shutdown starts every close before waiting for any, so a cancelled
    shutdown leaves no endpoint open, and a close error nobody reads is marked read, so
    asyncio never prints its text. Two new tests failed before the change.
  - Fixed in `d0c7545e2`: a new availability test traps the hidden pair's Connection read; it
    fails when the skip is moved below that read, which the earlier test missed.
- **Third review (2026-10-27),** an external review of `c14b811a2`: one finding, fixed in
  `61fbae090`.
  - The endpoint's adapter revision was part of every cache key but was never registered, so
    the community pages, the snapshot manifests and the importer's comparison never named it.
    Rows keyed under another revision of this adapter would load cleanly and never hit; no wrong
    hit was possible, as the revision is in the hash. The module now registers one revision for
    every configured endpoint, `remote_endpoint_adapter`, as the OpenRouter adapter does. Four
    new tests failed before the change: the gateway reports the revision its keys embed, a cache
    page holding an endpoint row names it, a snapshot manifest names it, and a page keyed under
    another revision is refused.
  - Rollout: a snapshot import compares only the names its manifest declares. A manifest from a
    gateway without this change still loads; a new manifest sent to an older gateway is refused
    with `revision_mismatch` unless forced, so the importing gateway upgrades first.
  - Only composition imports the module; the bundled plugin loader does not. The SDK's local
    pull check builds its revision set from that loader alone, so it neither requires nor checks
    this name: a pull from an older hosted gateway is not refused, and a change of this revision
    is not caught on pull. The SDK comment that every hosted row is an OpenRouter row is now out
    of date. Both belong to the SDK package and are left for a separate unit.
  - Already on main and out of scope: the Anthropic, Hugging Face and OpenAI adapters also put
    a revision into their keys without registering it.
  - Open, awaiting the owner: this review calls cache metadata public by accepted decision. The
    hosted BYOM design leaves metadata visibility to the endpoint access policy and keeps it
    apart from the shared replay of results, so the second review's "match the governing
    decisions" holds for the cache hit but is not settled for the listing. The comment cleanup
    waits on that choice.
- **Deviations:**
  - A removed alias is never served from the cache, but the two refusals differ: on a bypass the
    route resolves the caller's key before `prepare_chat_body`, so an account holding a key gets
    `invalid_model` and an account without one gets the no-key refusal. No upstream call either
    way; the test asserts both.
  - DNS labels accept `_`, read from "including Docker service names".
  - A bracketed host that is not an address (`http://[private-host]`) used to put the host
    text in the config refusal through the URL parser's message; the parse is now wrapped and the
    refusal echoes nothing. The same echo existed in Unit 0 for HTTPS origins.
  - The `max_tokens` rule keeps `projection_revision`: its wire mapping is unchanged, and no row
    was ever stored for this provider.
  - The pool bound is httpx's own default (100 connections, 20 kept alive); core admission caps
    concurrent calls per provider first.
  - Left unchanged, pending owner approval: the docstring of `test_app_cache_order.py` still says
    the instance inherits `CacheBypass`, which is no longer true. The test itself still passes.
  - Known limit: a chat already in flight when shutdown closes its endpoint client gets httpx's
    closed-client error as a 500. The server drains in-flight requests before the lifespan
    shutdown runs, so this window is not handled in code.
