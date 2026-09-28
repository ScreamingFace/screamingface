---
ticket: OME-1169
stack: screamingface
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1169 — The local stack refuses a foreign database setting and prints its effective config

## Intent

Two silent failures burned money during the OME-1098 golden recordings: `AIGATEWAY_DATABASE_URL`
is silently overridden by the local runtime's hard-coded sqlite path, and `screamingface up`
prints nothing about the config the gateway actually booted with (so a cache flag that never
reached the background child is invisible). This unit makes the mis-set environment fail loudly
at boot and puts the effective gateway config (db target + request-cache state) in the ready
banner, sourced from the settings object the gateway was constructed with.

Design decision (per the ticket, silence being the only unacceptable option): the local stack
keeps managing its own sqlite database; a set `AIGATEWAY_DATABASE_URL` is **refused at boot**
with remediation, not honored.

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/server.py` — compute a gateway config
  summary (redacted db url + request_cache on/off) from the constructed `GatewaySettings`;
  print it to the runtime log; publish it to the state file via a callback threaded from the
  serving CLI.
- `packages/screamingface/src/screamingface/_runtime/cli.py` — refuse `up`/`restart` when
  `AIGATEWAY_DATABASE_URL` is set; print the published gateway config line in the ready banner
  and in the adoption ("already running") banner; state-merge helper.
- `packages/screamingface/tests/test_runtime_cli.py` — new tests (append-only).

## Test plan

- RED: `up` with `AIGATEWAY_DATABASE_URL` set raises with a message naming the variable and the
  remediation (invariant: the local stack never silently records into a database other than the
  one the operator configured).
- RED: `up` with no such env does not refuse (default behavior unchanged — existing adoption
  tests double as this guard).
- RED: db-url redaction strips userinfo (`postgresql://u:p@h/db` → `postgresql://***@h/db`),
  leaves sqlite paths untouched (invariant: the banner never prints secrets).
- RED: gateway config summary reflects the settings values (cache on/off, db url).
- RED: publishing the summary merges it into the state file without dropping owner fields.
- RED: adoption banner prints the RUNNING stack's config from state; ready banner prints it
  after a fresh boot.

## Acceptance

- `screamingface up` with `AIGATEWAY_DATABASE_URL` exported exits with the loud refusal.
- The ready/adoption banner carries `gateway db=… · request_cache=on|off` sourced from the
  child's constructed settings via the state file; userinfo redacted.
- No env set → behavior byte-compatible except the added banner line.
- All prior tests green, gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_runtime/server.py` (redaction + summary + publish hook in
  `run`/`_build_apps`), `_runtime/cli.py` (refusal, banner line, publish closure),
  `tests/test_runtime_cli.py` (7 appended tests); plus this ledger + the `docs/tasks/` mirror.
- **Commits:** `fix(py-screamingface): refuse a foreign gateway database and print the
  effective config at up` (sha in the Linear close comment at merge).
- **Gates:** `run_gates.py screamingface` ALL GREEN — ruff check, ruff format, pyright,
  pytest (`--cov-fail-under=95`, 7 new tests, all prior tests unmodified), notebook check,
  build, distribution check.
- **Deviations:** none. Design fork resolved per the ticket's own framing: `AIGATEWAY_DATABASE_URL`
  is refused at boot (also on adoption), not honored — the local stack keeps its own sqlite.
- **Review follow-up (`d48fa21c`):** two PR #891 findings fixed — (1) `restart` now refuses
  BEFORE `down`, so a mis-set env can no longer stop a healthy stack and then raise; (2) the
  suite's autouse fixture scrubs `AIGATEWAY_DATABASE_URL`, so the refusal cannot fail
  pre-existing tests on a dev machine that exports it. One appended test; the fixture edit
  was owner-directed (append-only gate green post-commit).
