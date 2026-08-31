---
ticket: OME-990
stack: screamingface
status: in_progress
started: 2026-08-31
finished:
---

# OME-990 — Stop writing prompt-bearing query strings into `runtime.log`

## Intent

A local run starts as `GET /?q=<url4 expression>`, and a url4 expression is prompt-bearing by
construction — it carries the user's prompt text structurally. uvicorn's access logger is left
at its default (on), so every local run writes the user's prompt into
`<data_dir>/runtime.log`, a file created with mode `0644`.

This is the first rung of the observability programme (epic `OME-935`, spec
`docs/spec/2026-08-22-observability-traceability-review.md` — still on PR #688 at the time of
writing) and it is deliberately sequenced ahead of every tracing-wiring change. That
programme ends in "attach your logs to a report" (Phase 3); shipping that while prompts sit
in cleartext in a world-readable file converts a local exposure into an exfiltration path.
The one-line fix must land first.

Source: `docs/observability-state-of-play.md` — "Two security defects turned up along the way.
One has a one-line fix and should land before anything else."

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/server.py` — `_server()`, the shared
  factory booting the **gateway** and the **engine**: pass `access_log=False` to
  `uvicorn.Config`.
- `packages/screamingface/src/screamingface/_runtime/runtime_logging.py` — `_open_private()`,
  used by both `RuntimeLog.__init__` and `_rotate`, so the log is created `0600` **and** an
  existing world-readable log is tightened on reopen. The Linear issue names this in its own
  Verify line ("check the file mode while there") and calls the `0644`/`0600` split with
  `runtime.json` an aggravating detail.
- `packages/screamingface/tests/test_runtime_cli.py` — a test asserting *every* uvicorn
  configuration the runtime builds disables access logging (without booting a server), plus
  three file-mode tests (create, remediate-on-reopen, survive-rotation).

**Not in this unit** — `run_scoreboard()` (`server.py:258`) also omits `access_log`, but it
runs in a separate interpreter and its query strings are leaderboard filters (`?top=<int>`),
never prompts. Testing it means stubbing five runtime-extra imports for no prompt-leak value;
it goes to the follow-up below rather than inflating this unit.

## Test plan

RED first, behaviour-named, matching the house style in `tests/test_runtime_cli.py`:

- Every uvicorn configuration the local stack constructs disables the access log — asserted
  over the **whole sweep** (gateway *and* engine), not a single call.

The sweep is the point, not pedantry. uvicorn's `access_log=False` clears the
`uvicorn.access` handlers only for the Config being constructed at that moment, while every
later Config re-runs `dictConfig` and re-creates them, and the HTTP protocol re-reads
`hasHandlers()` per connection. A test asserting one server would pass while a second server
silently re-armed request logging for the whole process.

## Acceptance

- Every uvicorn server the client runtime starts in-process has access logging disabled.
- A local run no longer writes `GET /?q=<expression>` access lines into `runtime.log`.
- `runtime.log` is `0600` on creation, on reopen of an existing wider-moded file, and after
  rotation.
- No prior test modified; `run_gates.py screamingface` green (incl. `--cov-fail-under=95`).

**Deliberately NOT claimed:** that `runtime.log` is free of prompt text. The adversarial
review (below) proved that is a stronger statement than this change can support.

## Adversarial review — `access_log=False` is necessary but NOT sufficient

A three-agent investigation workflow swept the start sites, the test conventions, and the
sufficiency of the fix. The sufficiency verdict was **not sufficient**, with each finding
empirically reproduced rather than reasoned. Recorded here so the follow-ups are not lost
and so nobody reads this ticket as "prompts are out of the log now".

1. **`runtime.log` is the process's entire stdout+stderr**, not an access log.
   `capture_runtime_log` (`runtime_logging.py:89-92`) swaps both streams wholesale, so any
   library print, `warnings.warn`, traceback, or WARNING+ record from an unconfigured logger
   (via `logging.lastResort`, which resolves `sys.stderr` at emit time) lands in the file.
   `access_log=False` removes exactly one producer from that set.
2. **The flag is a process-global logger mutation, not a server property.**
   `uvicorn/config.py:421-423` clears `uvicorn.access`'s handlers, but every later
   `uvicorn.Config` re-runs `dictConfig(LOGGING_CONFIG)` and re-creates them;
   `h11_impl.py:57` re-reads `hasHandlers()` per connection. This is why the test asserts
   the whole sweep — a single-server assertion would ship this regression green.
3. **`uvicorn.error` logs the full path with query string on the WS path**
   (`websockets_impl.py:280/297/307`), which this flag does not touch — and the engine's WS
   URL is `/ws?ticket=<capability JWT>`, so a live token sits in the same file.
4. **Nothing remediates what is already on disk.** `runtime.log` is opened without a chmod
   (`runtime_logging.py:35,84`) — contrast `cli.py:702`, which chmods `runtime.json` to
   `0600` — and `LOG_BACKUPS = 5` keeps up to six historical files of already-leaked prompts.

Lower-severity, same file: litellm's module-level `StreamHandler` binds to the RuntimeLog
because litellm is imported *inside* the capture, so `LITELLM_LOG=DEBUG` turns the log into a
full prompt/completion transcript; and prompt text is embedded in url4/litellm exception
*messages*, kept out today only by first-party discipline with no sink-level control.

Finding 4 is **addressed in this unit** — `_open_private` creates the log `0600` and
tightens an existing world-readable one on reopen — because the Linear issue asks for it
directly. Its second half is not: **rotated backups** (`runtime.log.1` … `.5`) written by an
earlier version keep their old mode until they rotate through, and no pass removes the
prompts already inside them.

**Follow-ups to file** (none block this PR): remediate existing rotated backups; suppress the
`uvicorn.error` WS ticket line; pin `litellm.redact_messages_in_exceptions` and neutralise
`LITELLM_LOG` in the runtime env; install a redacting `setLogRecordFactory` for the capture's
lifetime (aigateway already ships that pattern at `core/auth/log_filter.py:71-85`);
`access_log=False` in `run_scoreboard()`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `_runtime/server.py` (one `uvicorn.Config` call);
  `_runtime/runtime_logging.py` (`_open_private` + both open sites);
  `tests/test_runtime_cli.py` (4 tests + 1 helper, appended);
  `docs/tasks/2026-08-25-OME-990-runtime-log-prompts.md` (mirror).
- **Commits:** `fix(screamingface): stop logging prompt-bearing query strings` (sha assigned
  at squash-merge).
- **Gates:** `run_gates.py screamingface` — **ALL GATES GREEN**: append-only test check (vs
  HEAD) · ruff check · ruff format --check · pyright · `pytest --cov=screamingface
  --cov-fail-under=95` (**1281 passed, 17 skipped**) · check_notebooks · uv build ·
  check_distribution. RED was confirmed first: the new test failed on
  `options.get("access_log") is False` with both configs constructed and every other
  assertion passing.
- **Deviations:** `run_scoreboard()` deliberately left unchanged (rationale above) — the
  ledger's original acceptance criterion ("a local run leaves no `?q=` in `runtime.log`") was
  narrowed after the adversarial review showed it overstated what this change achieves.
