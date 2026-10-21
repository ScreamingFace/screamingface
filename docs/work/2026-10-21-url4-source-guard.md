---
ticket: OME-1544
stack: url4
status: blocked
started: 2026-10-21
finished:
---

# url4-source-guard — one destination guard for url4 HTTP source fetches

## Intent

Implement spec F1b (`docs/spec/2026-10-16-OME-1535-file-input-execution.md`, commit `3c6ae278e`):
every `https://` source fetch in `packages/url4` passes through one destination guard in the
HTTP transport (scheme policy, address refusal after DNS with IP pinning that keeps SNI/`Host`,
per-hop redirect re-check with a hop limit and no `https`→`http` downgrade, connect timeout plus
one total deadline, streaming decoded-byte cap, typed `x.source_*` errors). Fixes bug `OME-1704`.
Epic `OME-1529`.

## Plan (F1b)

- `src/url4/io/_source_guard.py` (new): address policy (`ipaddress`, IPv4-mapped IPv6 unwrapped,
  decimal/hex IPv4 host forms normalized), injectable resolver, guarded httpx transport that
  connects to the vetted IP with `sni_hostname` + original `Host`, `trust_env=False`.
- `src/url4/core/errors.py`: `x.source_destination_blocked` / `x.source_redirect_limit` /
  `x.source_too_large` (permanent), `x.source_timeout` (retryable).
- `src/url4/io/http.py`: the owned client is built on the guarded transport; redirects re-checked
  per hop; body streamed under the cap; total deadline around the whole fetch.

## Test plan

Mocked resolver/transport only: 127.0.0.1, 10.0.0.1, ::1, ::ffff:127.0.0.1, 169.254.169.254,
decimal/hex IPv4 hosts, userinfo trick, DNS → private, public→private redirect, 4-hop chain,
https→http downgrade, non-http `Location` scheme, gzip oversize aborted mid-stream, slow-drip total
deadline, env proxies ignored, allowed public IP succeeds with SNI/`Host` preserved.

## Acceptance

All F1b rules hold on the default (owned) `HttpIOLayer` client; `run_gates.py url4` green without
`--skip-append-only`.

## Outcome

- **Status:** BLOCKED before RED — append-only test conflict plus one design fork (see below).
- **Blocker 1 (append-only):** `tests/regressions/test_close_safety.py::mock_owned_client`
  monkeypatches `httpx.AsyncClient` with `factory(**kw)` that calls
  `real(transport=_SlowCloseTransport(_ok), **kw)`, then fetches `https://x/` through the OWNED
  client and expects `"BODY"` (4 tests). Installing the guard on the owned client needs either
  `transport=` (→ `TypeError: multiple values for 'transport'`) or `mounts=` / a DNS check outside
  the transport (→ the guard resolves the unresolvable host `x` and refuses it). The only way to keep
  the fixture unchanged is a production branch that skips the guard when the client's private
  `_transport` is not a real `AsyncHTTPTransport` — test-shaped, rejected.
- **Blocker 2 (design fork):** `url4://` targets are rewritten to `https://` and fetched by the same
  layer (remote node calls). F1b names "every source fetch"; guarding them refuses url4 peers on
  private/cluster addresses unless an allowlist exists (F1b only defines a loopback escape hatch).
- **Commits:** ledger only.
- **Gates:** not run (no code change).
- **Deviations:** stopped per the append-only rule.
