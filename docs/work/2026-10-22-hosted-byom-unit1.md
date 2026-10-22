---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: aigateway
status: planned   # planned | in_progress | done | blocked
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
  client per endpoint, created on first use and closed at application shutdown.
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
