---
ticket: OME-1544
stack: url4
status: done
started: 2026-10-21
finished: 2026-10-21
---

# url4-source-guard — one destination guard for url4 HTTP source fetches

## Intent

Implement spec F1b (`docs/spec/2026-10-16-OME-1535-file-input-execution.md`, commits `3c6ae278e` +
`f1b70663a` on `OME-1535-file-input-execution-spec`): every source fetch on the default (owned)
`HttpIOLayer` client passes through one destination guard in the url4 HTTP transport (scheme policy,
address refusal after DNS with IP pinning that keeps SNI/`Host`, per-hop redirect re-check with a hop
limit and no `https`→`http` downgrade, connect timeout plus one total deadline, streaming decoded-byte
cap, typed `x.source_*` errors). `url4://` remote-node calls are guarded too: same address rules plus
an operator-configured peer-host allowlist. Fixes bug `OME-1704`. Epic `OME-1529`.

## Owner decisions (Linear OME-1544, 2026-10-21 12:54Z, "Owner decisions")

1. Approved fixture edit: `tests/regressions/test_close_safety.py::mock_owned_client` becomes
   `real(**{**kw, "transport": _SlowCloseTransport(_ok)})`; assertions unchanged. Recorded in
   `.claude/test-change-approvals/OME-1544.json` (pinned to branch `url4-source-guard`; update the
   manifest's `branch` if the branch is renamed to `OME-1544-*` at PR-open).
2. `url4://` remote-node calls are guarded: address rules + peer-host allowlist.
3. "Fetched once per run" moved to `OME-1543`; not in this unit.
4. Attachment scope (`src=` bindings) is `OME-1543`'s; not in this unit.

## Compatibility check (peer-allowlist default)

Searched `origin/main` (engine config `url4.toml` / `deploy/kind/url4-kind.toml`, `apps/*/charts`,
engine/SDK source, tests, docs) for `url4://` remote-node calls in real use: none. The engine builds
`Url4Node(outbound=None | StaticIOLayer())` — the default `HttpIOLayer()` — and no deployment names a
peer. `url4://` occurrences are parse-only tests, studio recipe strings, and the url4 package's own
`Client("url4://host")` API docs (the example notebook injects its own client). So the default is
**empty** (spec F1b). Configuration path: `HttpIOLayer(guard=SourceGuard(peer_hosts=...))`.

## Planned changes

- `src/url4/io/_source_policy.py` (new, stdlib only): `SourceGuard` config, address policy
  (`ipaddress`, IPv4-mapped IPv6 unwrapped, decimal/octal/hex IPv4 host forms normalized), scheme and
  peer checks, typed error constructors.
- `src/url4/io/_guarded_transport.py` (new): httpx transport that resolves through an injectable
  resolver, vets every answer, and connects to the vetted IP with `sni_hostname` + original `Host`.
- `src/url4/core/errors.py`: `x.source_destination_blocked` / `x.source_redirect_limit` /
  `x.source_too_large` (permanent), `x.source_timeout` (retryable).
- `src/url4/peer/_http.py`: statuses 422 / 422 / 413 / 504 (spec §4).
- `src/url4/io/http.py`: owned client on the guarded transport (`trust_env=False`,
  `follow_redirects=False`); redirects re-checked per hop; body streamed under the cap; one total
  deadline. Relative fetches against the operator-set `base_url` origin stay trusted.
- `tests/unit/test_source_guard*.py` (new); the approved fixture edit; the approval manifest.

## Test plan

Mocked resolver/transport only: 127.0.0.1, 10.0.0.1, ::1, ::ffff:127.0.0.1, fc00::1, 169.254.169.254,
100.64.0.1, decimal 2130706433, octal 0177.0.0.1, hex 0x7f.1, userinfo `https://a@127.0.0.1`, DNS name
→ private, DNS rebinding (public then private; connect pinned, SNI/`Host` kept), public→private
redirect, relative `Location` to a private host, 4-hop chain, https→http downgrade, non-http(s)
`Location`, gzip oversize aborted mid-stream, slow-drip total deadline, `trust_env=False`, `url4://`
peer off the allowlist blocked, allowlisted peer ok, allowed public IP ok, loopback only when
configured.

## Acceptance

All F1b rules hold on the default (owned) `HttpIOLayer` client; `run_gates.py url4` green without
`--skip-append-only`.

## Outcome

- **Status:** DONE (code + tests; PR not opened by this run).
- **Actual files:** as planned, plus `src/url4/io/__init__.py` (doc), `src/url4/peer/client.py`
  (doc: owned adapter has an empty peer allowlist), `README.md` (feature note),
  `.claude/test-change-approvals/OME-1544.json`. New tests: `tests/unit/test_source_guard_policy.py`,
  `tests/unit/test_source_guard_http.py`.
- **Commits:** `81bc89f13` feat(url4): guard HttpIOLayer source fetches by destination (F1b).
- **Gates:** `run_gates.py url4` ALL GATES GREEN (append-only via the approved manifest, no
  `--skip-append-only`); `run_gates.py screamingface-engine` ALL GATES GREEN (not touched; run
  because it consumes url4 editable); `check_module_size.py` and `check_suppressions.py` within
  baseline.
- **Defaults chosen (spec leaves values to the leaf):** `max_redirects=3`, `max_bytes=20 MiB`
  (decoded), `connect_timeout=10s`, `total_timeout=60s`, `peer_hosts` empty, `allow_http` and
  `allow_loopback` off. Config path: `HttpIOLayer(guard=SourceGuard(...), resolver=...)`.
- **Deviations:**
  - Redirects are followed by httpx (`follow_redirects=True`, `max_redirects=guard.max_redirects`)
    and every hop is re-checked in `GuardedTransport`, not in a hand-written loop — this keeps the
    prior test `test_owned_client_follows_redirects` unchanged. httpx reads redirect bodies itself,
    so the transport also caps raw bytes per response.
  - Pinning rewrites the request to the vetted IP with `sni_hostname` + the original `Host`, one
    connection pool per host name (no httpcore import / private `_pool` swap).
  - An injected `client` gets only the size cap; destination rules and the total deadline apply
    to the owned client (its owner chose destinations and timeouts). Relative fetches to the
    operator-set `base_url` origin are trusted; a redirect off that origin is guarded.
  - An allowlisted peer is still subject to the address rules (spec F1b text), so a peer on a
    private/cluster address is refused unless `allow_loopback` covers it (loopback only).
  - Read/pool timeouts other than connect keep their old `resolution_failed` mapping; only the
    connect timeout and the total deadline map to `x.source_timeout` (spec §4 row).
  - Approval manifest is pinned to branch `url4-source-guard`; when the branch is renamed to
    `OME-1544-*` at PR-open, update the manifest's `branch` field.
- **Rebase vs `origin/OME-1538-url4-bytes-fetch` (#1478):** probe merge conflicts only in
  `io/http.py` `_get` (signature `_get(url, accept=None)` + headers dict vs this unit's
  `_get(target)` + `_send`) and the helper block (`_media_type`/`_text` vs
  `_trusted_origins`/`_read_capped`/`_buffered` — keep both). Resolution: `_get(target, accept=None)`
  translates `url4://`, builds the headers dict with `Accept`, and calls `_send(url, headers or None,
  peer=peer)`. With that resolution the merged url4 suite passed (2070 passed, ruff + pyright clean),
  and `fetch_bytes` inherits the guard through `_get`.

## Review hardening (adversarial review, 2026-10-21)

Three F1b bypasses found after `ad932ceb4`, each fixed test-first (RED observed, then GREEN);
no existing test changed.

1. **Decompression bomb** — httpx inflated a whole raw chunk before the cap ran
   (`gzip(gzip(1 GiB))` peaked ~2.2 GB RSS at `max_bytes=1 MiB`). The guarded transport now sends
   `Accept-Encoding: identity` and decodes at most ONE `gzip`/`deflate` layer itself
   (`src/url4/io/_body_decode.py`, zlib `decompressobj` with `max_length=64 KiB` per step,
   `Content-Encoding`/`Content-Length` stripped so httpx does not decode again). Tests:
   `test_nested_gzip_bomb_peak_memory_bounded`, `test_single_gzip_bomb_peak_memory_bounded`
   (tracemalloc peak < 2×cap), identity request, single-layer decode matrix, refusal matrix,
   corrupt body. Commit `426689ec6`.
2. **Reserved / embedded IPv6** — `vet_address` now refuses `is_reserved` and `192.88.99.0/24`
   (6to4 relay), and `_unwrap` judges IPv4-compatible `::/96` and SIIT `::ffff:0:0:0/96` as the
   embedded IPv4 (`::` and `::1` excluded). Tests: `test_reserved_and_embedded_ipv4_forms_are_refused`,
   `test_embedded_loopback_forms_follow_the_escape_hatch`. Commit `68a718c2d`.
3. **Redirect into the base_url origin** skipped every check. Trust is now a one-shot
   `FetchState.trusted_first_hop`, set only for a relative fetch whose URL is on the base_url
   origin; every redirect hop (including back into that origin), an absolute target spelling the
   origin, and a transport call without `FetchState` are checked. Tests:
   `test_redirect_into_base_origin_still_checked` + 3 siblings. Commit `003e99516`.

**Deviations (for the PR reviewer):**
- Stacked or unsupported codings are refused as `x.source_too_large` (not
  `x.source_destination_blocked`): spec §4 binds `too_large` to the decoded-byte cap, and these
  codings are refused because that cap cannot be enforced layer by layer; `destination_blocked`
  is about where a hop goes (scheme/address/downgrade/peer).
- `br` is refused, not decoded: no brotli decoder is a url4 dependency, and adding one is a new
  dependency (out of this unit). With `Accept-Encoding: identity` a compliant server never sends it.
- The trusted first hop now also goes through the bounded decoder + cap (previously its body was
  passed through untouched).
- Unchanged by instruction: an injected `client` still gets only the size cap, checked after
  httpx's own decoding — so it is NOT bomb-safe; its owner chose its decoding.

**Gates:** `run_gates.py url4` ALL GATES GREEN (no `--skip-append-only`);
`run_gates.py screamingface-engine` ALL GATES GREEN; `check_module_size.py` / `check_suppressions.py`
within baseline (suppressions 5/5).
