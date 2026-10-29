---
ticket: OME-1772
stack: url4
status: done
started: 2026-10-29
finished: 2026-10-29
---

# url4-refuse-userinfo — the url4 source guard refuses URLs with embedded credentials

## Intent

`SourceGuard` admits `https://user:pass@host/x`, and httpx then sends `Authorization: Basic …`
to that host. HupBaHa's review of #1586 found it; OME-1552's acceptance requires credentialed
URLs never to be fetched. The guard now refuses any URL whose authority carries userinfo
(password, username only, or empty `@`) with the existing permanent
`x.source_destination_blocked`, before any DNS lookup or connection — on the first hop and on
every redirect hop. Owner decision (Sergey, 2026-10-28): a separate small PR under epic OME-1529.

## Planned changes

- `packages/url4/src/url4/io/_source_policy.py` — `check_destination(..., credentials=)` refuses
  userinfo; `check_url` passes `"@" in netloc` (stdlib parse, so the empty `https://@host`, which
  httpx normalizes away, is still seen).
- `packages/url4/src/url4/io/_guarded_transport.py` — every guarded hop passes
  `credentials=bool(url.userinfo)`, so a redirect to a credentialed `Location` is refused.
- `packages/url4/tests/unit/test_source_guard_userinfo.py` — new (append-only).

## Test plan

- Policy: `check_url` refuses `user:pass@`, `user@`, `@`, `:@`; `%40` in path/query is allowed;
  the refusal message never echoes the credentials.
- HttpIOLayer owned client (fake resolver + MockTransport): each credentialed spelling is refused
  with no lookup and nothing on the wire (so no `Authorization`); `fetch_ex` too; `%40` in
  path/query is fetched with no `Authorization`; a 302 to a credentialed `Location` is refused
  after the first hop only and no request carries `Authorization`; a request built outside
  HttpIOLayer is refused by the transport alone.

## Acceptance

- Credentialed URLs are refused with `x.source_destination_blocked` (permanent) before any I/O.
- `run_gates.py url4 --base origin/main` green; `check_module_size.py` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus a one-line `HttpIOLayer` docstring mention in
  `packages/url4/src/url4/io/http.py`.
- **Commits:** see branch `url4-refuse-userinfo` — `fix(url4): refuse source URLs with embedded credentials`.
- **Gates:** `run_gates.py url4 --base origin/main` ALL GATES GREEN (append-only, ruff, format,
  pyright, pytest cov>=95: 2164 passed, 17 xfailed); `check_module_size.py` within baseline
  (io/ modules are uncapped; `_source_policy.py` 214→222, `_guarded_transport.py` 359→364).
- **Deviations:** `fetch_bytes` (PR #1478) is not on main, so it has no test here. The refusal
  lives in `check_url` + `GuardedTransport` (every owned-client hop), so a bytes path that goes
  through the owned client is covered once it lands; #1478 should add its own bytes test.
  The trusted first hop of a RELATIVE fetch against the operator's `base_url` stays exempt
  (spec F1b: the operator's origin is outside the guard); every redirect hop is checked.

## Review round 1 — HupBaHa CHANGES_REQUESTED (2026-10-29 15:40, head `11b63d1`)

1. **Medium — malformed credentialed authority echoed in the error.** `check_url()` returned on
   a `urlsplit()`/`.hostname` `ValueError`, then `_send()` wrapped httpx's `InvalidURL` with the
   raw target (`https://user:pass@[::1` → message carried the credentials).
   Fix: `_source_policy.has_userinfo()` reads the authority lexically (after optional scheme +
   `//`, up to the first `/ ? #`, httpx's own delimiting; urlsplit's C0/space strip and
   tab/newline drop applied) BEFORE any strict parse; `check_url` refuses a credentialed
   malformed URL with the same permanent `x.source_destination_blocked`, raised outside any
   handler (no chained parse error). `http._failure()` reports a credentialed `InvalidURL`
   (injected client / trusted path, where `check_url` does not run) as
   `GET 'https://***@…' failed: invalid URL` — redacted, no httpx detail, nothing chained.
   `_send` now raises outside its handler, chaining only the error `_failure` names.
2. **Low — empty-userinfo redirect normalized before `_pinned()`.** HTTPX 0.28.1 turns
   `Location: https://@other.example/x` / `//@other.example/x` into an empty userinfo before the
   next hop. Owner choice: keep the strict every-hop contract. Redirects are followed by httpx
   (`follow_redirects=True`), so `GuardedTransport` now checks the RAW `Location` of every
   redirect response it returns (`_refuse_credentialed_location`), closes that body, and refuses
   — before httpx builds the next request, so the second host is never looked up.

- **Tests (appended, none edited):** 5 malformed first-hop forms (unclosed bracket ±path,
  bracketed non-address, bracketed bad port, named bad port) × {`check_url`, owned-client fetch
  (no lookup, nothing sent), injected-client fetch (httpx `InvalidURL` path)} assert the
  username and password are absent from `str`/`repr`/notes of the error and every
  `__cause__`/`__context__`; a new redirect matrix (`https://@`, `//@`, `https://:@`) asserts
  refusal, only the first hop sent, only `example.com` looked up.
- **Gates:** `run_gates.py url4 --base origin/main` ALL GATES GREEN (2182 passed, 17 xfailed);
  `check_module_size.py` within baseline, no cap raised (io/ modules uncapped:
  `_source_policy.py` 272, `_guarded_transport.py` 381, `http.py` 346). Ruff's branch/statement
  limits on `_send` were met by extracting `_failure`/`_wrapped`, not by suppressions.
- **Residual, out of scope:** an HTTP status error on a well-formed credentialed URL sent via the
  operator-trusted `base_url` or an injected (unguarded) client still repeats httpx's message,
  which includes the URL — both paths are trusted by design (review: not a finding).
