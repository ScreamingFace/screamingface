---
ticket: OME-1050
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# runtime-log-sink-redaction — redact structural prompt carriers at the runtime log sink

## Decision (owner, 2026-10-01)

The ticket as filed contradicted itself. A redacting record factory cannot satisfy a Verify
that includes `print`, `warnings.warn` and tracebacks, because I measured that none of those
create a `LogRecord`. "Prompt-shaped" was also undefined. Sergey chose **option A**, quoted
from the coordinator:

> OME-1050 option A. Pin `litellm.redact_messages_in_exceptions = True`, and neutralise
> `LITELLM_LOG` in the runtime env (mirror request_hardening.py). Add a WRAPPING record
> factory (preserve any already-installed one) plus line-level redaction in
> `RuntimeLog.write`, for structural carriers only: url4 `?q=` query values, litellm's
> `Messages:` suffix, and the litellm curl `-d` body. Rewrite the Verify in the ledger to
> plant those structures through all four producers (print, warnings.warn, an unconfigured
> logger, a traceback) and assert none reach runtime.log. Also test that the factory
> preserves a pre-installed one. Document that unmarked free text is out of scope.

## Intent

`runtime.log` is the process's whole stdout/stderr sink. Prompt text leaks into it today
through structural carriers:

- url4 `?q=` query values, inside exception messages and URLs;
- the `Messages:` suffix that litellm appends to exceptions;
- litellm's debug curl `-d` body.

Redact those carriers at both choke points: the record factory, and every line
`RuntimeLog` writes. Also switch off the two litellm producers at source.

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/log_redaction.py` (new). It holds:
  - the three patterns and `redact()`;
  - a wrapping `redacting_record_factory()` context manager, which preserves the installed
    factory and is idempotent over the chain.
- `.../_runtime/runtime_logging.py`:
  - `RuntimeLog._write_line` redacts each line;
  - `capture_runtime_log` installs the factory for its lifetime.
- `.../_runtime/bootstrap.py`:
  - `neutralise_litellm_debug(environment)` sets `LITELLM_LOG=WARNING`, overriding the
    user's value. Unsetting the variable would not work, because litellm's default is
    `DEBUG`.
  - `pin_litellm_redaction()` sets `litellm.redact_messages_in_exceptions = True`.
- `.../_runtime/server.py`:
  - `require_runtime_extra` neutralises `LITELLM_LOG` before any app import;
  - `run` pins the litellm flag.
- `packages/screamingface/tests/test_runtime_log_redaction.py` (new).
- README and CHANGELOG. These document that unmarked free text is out of scope.

## Test plan (the rewritten Verify)

- Each of the three carriers is planted through each of the four producers inside
  `capture_runtime_log`: `print`, `warnings.warn`, an unconfigured third-party logger
  (lastResort), and an uncaught-style traceback (`sys.excepthook`). The planted secret is
  absent from `runtime.log`, and the surrounding non-secret text is present.
- The factory preserves a pre-installed factory: its side effect still applies inside the
  capture, and the pre-installed factory is restored on exit. The factory is idempotent
  when nested.
- Records are redacted for any handler, not only `RuntimeLog`, by checking
  `record.getMessage()` from the factory.
- `redact()` boundaries:
  - it leaves text without a carrier unchanged;
  - it redacts `&q=` and a quoted URL;
  - it leaves non-`q` parameters alone.
- `neutralise_litellm_debug` overrides `DEBUG` and sets the variable when it is absent.
- `pin_litellm_redaction` sets the flag on a stub `litellm`.
- `require_runtime_extra` neutralises the environment, checked with stub modules.

## Acceptance

- No planted carrier secret reaches `runtime.log` through any of the four producers.
- A pre-installed record factory still runs.
- Out-of-scope free text is documented.
- Gates are green, prior tests are unmodified, and the mirror is `in_review` with
  `check_mirror_status` exiting 0.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `log_redaction.py` is new. `runtime_logging.py`,
  `bootstrap.py` and `server.py` are wired. `tests/test_runtime_log_redaction.py` adds 30
  tests: 3 carriers x 4 producers, plus the factory, `redact()`, litellm and boot tests.
  README, CHANGELOG and the `docs/tasks/` mirror are updated.
- **Commits:** `fix(screamingface): redact prompt carriers at the runtime log sink` (this
  ledger's commit).
- **Gates:** `run_gates.py screamingface` reports ALL GATES GREEN:
  - append-only, ruff, format and pyright;
  - pytest: 2133 passed / 26 skipped at 96% coverage;
  - notebooks, build and distribution. The wheel ships `_runtime/log_redaction.py`.
- **Mutation check:** I removed both choke points, the `redact()` call in `_write_line` and
  the factory in `capture_runtime_log`. 13 tests then failed: all 12 carrier x producer
  cases and the preserve test.
- **Empirical check (litellm==1.102.1, the pinned version):**
  - with `LITELLM_LOG=WARNING`, litellm's handler level is WARNING;
  - `redact_messages_in_exceptions` defaults to `False`, which is why it needs pinning;
  - `exception_mapping_utils` consults the flag.
- **Deviations:**
  - "Neutralise" sets `LITELLM_LOG=WARNING` and overrides any explicit user value. Unsetting
    it would not work, because litellm's default is DEBUG.
  - `pin_litellm_redaction()` runs in `server.run` (the serving child), not in
    `require_runtime_extra`, so that `up`, `status` and `doctor` do not pay litellm's import
    cost.
  - The `q=` value is redacted up to `&`, `#`, a quote or the end of the line, and NOT up to
    whitespace. An unquoted value therefore over-redacts the trailing context on that line.
    This fails closed by design, and a test pins it.
  - Factory restore happens only if ours is still on top, so a wrapper installed during the
    capture is never dropped.
  - The tests swap in a replica of stdlib `showwarning` and clear root handlers inside the
    producer. Without that, pytest's warning and log capture would mask the production
    paths. Each swap has a WHY comment.
  - Out of scope, by decision: unmarked free text, such as url4 parser errors quoting a bare
    expression, and litellm's RAW RESPONSE.

## Review round 1 (2026-10-02, owner decision on PR #1206)

Two confirmed defects were fixed. Each got RED tests first.

1. **The record factory raised at the logging call site.**
   - The cause: it caught only `TypeError` and `ValueError` from `getMessage()`.
   - The reproductions: `log.warning("%(a)s", {"b": 1})` raises `KeyError`, and an argument
     whose `__str__` raises gives `RuntimeError`.
   - The fix: catch `Exception` and leave the record untouched, so logging's own
     "--- Logging error ---" path applies.
   - The test builds its `Logger` outside the manager. Otherwise pytest's capture handlers,
     whose `handleError` raises, would mask the stdlib path.
2. **`_URL4_QUERY` stopped at a quote and leaked quoted Text intents.** url4 `_quote`
   renders them single-quoted with `\'` and `\\` escaped.
   - The value now includes `'…'` and `"…"` segments (escapes honoured) up to `&`, `#` or
     whitespace outside quotes, or the end of the line.
   - An unterminated quote fails closed to the end of the line. That includes a backslash
     at the end of a line, and a repr's closing quote.
   - New tests cover 5 quoted-intent shapes × 4 producers.
- **Expectations changed in tests added by THIS PR, because the owner's rule supersedes my
  earlier choice:**
  - In the factory-preserve test, the message is now `%s` (unquoted).
  - Two `redact()` cases encoded "whitespace continues the value". They are replaced by
    "whitespace outside quotes ends it" and the repr fail-closed case.
- **Trade-off:** `GET '<url>?q=abc' failed: …` now loses everything after `?q=` on that
  line, because the repr's closing quote fails closed. This was accepted per the
  fail-closed rule.
- **Rebase:** rebased onto origin/main. The README and CHANGELOG conflicts with #1205
  (OME-1048) were resolved by keeping both sides.
- **Gates:** `run_gates.py screamingface --base origin/main` reports ALL GATES GREEN. The
  base is origin/main because the test file is added in this PR. The full client suite with
  the notebook and runtime extras: 2187 passed, 26 skipped, 96% coverage.
