---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
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
