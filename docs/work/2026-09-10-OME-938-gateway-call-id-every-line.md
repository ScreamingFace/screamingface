---
ticket: OME-938
stack: aigateway
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-938 — Carry `gateway_call_id` on every aigateway log line

## Intent

Today the id appears on **exactly one** log line — `plugins/taxonomy/session.py:135`, and even
there it is interpolated into a message string. Every dispatch, cache, retry and concurrency
line in the same request is anonymous, so an operator holding a `gateway_call_id` from a
response body can find the one line that announces it and nothing about what the call actually
did.

Prerequisite for `OME-1120` (rung 4b): that unit joins the inbound `traceparent` to the same
context this unit establishes. Building the machinery once, with two fields, is why the order
is `938 → 1120` and not the reverse.

## Design decisions

**D1 — the injector WRAPS the existing record factory; it never replaces it.**
`install_provisioning_token_redaction` (`core/auth/log_filter.py:71-85`) owns the single
`logging.setLogRecordFactory` slot and already wraps whatever it found, guarded by an
idempotence flag. Replacing it would silently disable provisioning-token redaction — a
**security regression hiding inside an observability change**, and one no observability test
would notice. The same wrap-plus-flag shape is copied here, and a test asserts redaction still
fires after this injector is installed.

**D2 — render through a `%(call_context)s` slot and a Filter, mirroring the engine.**
`logs.py`'s `_FORMAT` is `"%(levelname)s:     %(name)s %(message)s"` — plain text. Setting an
attribute on the record therefore renders **nowhere**; the format has to carry it. The engine
solved this identically in `screamingface_engine/logs.py` with a `%(run_context)s` slot filled
by `RunContextFilter`, rendering `key=value` pairs. Mirroring it keeps two services' logs
readable as one stream and gives `OME-1120` a slot to add `trace_id` to. `defaults=` on the
Formatter keeps a record that reaches the handler without passing the filter from raising
KeyError.

**D3 — the id is generated in middleware, not in the taxonomy plugin.** `TaxonomyPlugin` is
gated by `TaxonomyPluginSettings().enabled` (`AIGW_TAXONOMY_ENABLED`), and it currently owns id
generation. So disabling a *usage-accounting* feature silently deletes the *only correlation
mechanism* — the foot-gun the issue names. Middleware generates; the plugin consumes what is
already bound.

**D4 — pure ASGI middleware, not `BaseHTTPMiddleware`.** The app's only existing middleware
(`AuthDisabledLocalOnlyMiddleware`) is `BaseHTTPMiddleware`, so that is the tempting model. It
is wrong for a ContextVar: `BaseHTTPMiddleware` runs the downstream app in a **separate task**,
so values set in `dispatch` reach the endpoint but the coupling is fragile, and this gateway
streams SSE — where the response body is produced after `dispatch`'s frame has moved on. Pure
ASGI middleware sets the var in the same task that runs the whole request, streaming included.

**D5 — the existing announce line keeps its text and gains the field.** `session.py:135`
interpolates `gateway_call_id=%s`. Once every line carries the id through the context, that
interpolation is redundant, but the line is asserted by an existing test
(`test_lifespan_and_correlation.py`). Left as-is rather than reworded — the append-only rule
makes rewriting a prior test's subject a Confidence-Gate decision for no behavioural gain.

## Out of scope, and why it is worth stating

**Whether logs become JSON is NOT decided here.** `OME-1118` requires "structured log fields
rather than ids interpolated into message strings, or the payoff degrades to grep-over-HTTP" —
and with a plain-text formatter, SigNoz gets a full-text-searchable `key=value`, not a filterable
attribute, unless the collector is taught to parse it. Switching the format is a **cross-app
infrastructure decision** (engine, aigateway and scoreboard would have to move together, plus the
collector config), not something this unit should settle unilaterally. This unit delivers the
`key=value` shape the engine already emits; raising the JSON question separately.

Also out of scope per the issue: LiteLLM callbacks (its telemetry plane is an attack surface
here), and request bodies are never logged.

## Planned changes

- `src/aigateway/call_context.py` (new) — the ContextVar, `call_scope()`, `current_call_id()`,
  and the record-factory installer that wraps the existing factory.
- `src/aigateway/middleware/call_id.py` (new) — pure ASGI middleware generating the id per
  request and binding the scope.
- `src/aigateway/logs.py` — `%(call_context)s` slot in `_FORMAT` + the rendering Filter.
- `src/aigateway/main.py` — install the injector beside the redaction install; register the
  middleware.
- `src/aigateway/plugins/taxonomy/session.py` — consume the bound id instead of minting one.
- Tests as below.

## Test plan

RED first:

- **A log record carries the `gateway_call_id` of the request that produced it** — asserted on
  dispatch, cache, retry and error paths, not one sampled line. A record-factory wrapper that
  misses a code path is precisely the defect this unit exists to remove.
- **Provisioning-token redaction still fires after the injector is installed** (D1). The
  security regression test; it must fail if the factory is replaced rather than wrapped.
- **Installing twice does not double-wrap** — idempotence, matching the redaction guard.
- **Correlation survives `AIGW_TAXONOMY_ENABLED=false`** (D3) — the foot-gun, asserted directly.
- **Two concurrent requests never share an id**, and neither leaks into the other's records.
- Outside any request no `gateway_call_id` renders — the boot/shutdown lines stay byte-identical.
- The existing response-id == log-id test still passes, extended to a second line.
- Ladder rung 3 (`test_rung3_every_gateway_log_line_carries_a_call_id`) flips green; **its strict
  xfail marker is deleted in this PR**.

## Acceptance

- Every log line emitted inside a request carries that request's `gateway_call_id`.
- Redaction demonstrably intact.
- Rung 3 green; rungs 4a/4b still xfail.
- `run_gates.py aigateway` green incl. the auth-surface coverage job.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `core/auth/log_filter.py` (the stacking fix, below) and
  two prior tests — `call_context.py`, `middleware/{__init__,call_id}.py`, `logs.py`,
  `main.py`, `plugins/taxonomy/{session,collector}.py`, `core/auth/log_filter.py`,
  `tests/unit/test_call_context.py` (13 new tests), plus the ladder and one accounting test.
- **Commits:** `feat(aigateway): carry gateway_call_id on every log line` (sha at squash-merge).
- **Gates:** `run_gates.py aigateway --skip-append-only` — **ALL GREEN** (ruff, ruff format,
  pyright, check_no_enterprise, `pytest --cov --cov-fail-under=80`): **4119 passed, 58
  skipped** (baseline 4107 — +12). `run_gates.py screamingface --skip-append-only` — **ALL
  GREEN**. Ladder against the real stack: **3 passed, 2 xfailed** — rung 3 flipped green.
- **Deviations:**
  - **A RecursionError, caused by this change and exposing a latent bug in the existing
    redaction installer.** First full-suite run: **85 failed, 435 errors**, all
    `RecursionError: maximum recursion depth exceeded` out of `log_filter.py` at *fixture
    setup*. Cause: two installers share `logging.setLogRecordFactory`, and each guard checked
    only whether the OUTERMOST factory was its own. So each installer saw the other's wrapper,
    concluded it had not run, and wrapped again — every interleaved pair adding two layers.
    `create_app` installs both and the suite builds thousands of apps, so the chain grew until
    creating one log record overflowed the stack. **The redaction installer had this flaw all
    along**; it was invisible while it was the only installer. Fixed by walking the wrapper
    chain (`factory_chain_has`, `__wrapped__` links) in BOTH installers, with a regression test
    asserting chain depth stays ≤3 across 50 interleaved install rounds. Baseline was verified
    green (4107 passed) before blaming the change, and it was correctly mine.
  - **The security test was written vacuous and caught before it mattered.** The first version
    asserted a secret-looking token was absent from a message that `RedactProvisioningTokenFilter`
    would never have matched — its pattern keys on `X-Aigw-Provisioning-Token` followed by
    `:`/`=`. The assertion would have passed whether or not the factory was wrapped. Rewritten
    against a genuinely matching message, and every redaction assertion now also requires
    `[REDACTED]` to be PRESENT, proving redaction ran. **Mutation-verified**: replacing the wrap
    with `logging.LogRecord(...)` makes the test fail, as it must.
  - **`factory_chain_has` lives in `core/auth/log_filter.py`, not beside the newer installer.**
    `core` must not import from the app root, and that module already owned the first factory.
  - **Rung 3's assertion was unsatisfiable and had to be scoped — the largest Confidence-Gate
    item here.** It asserted *every line in the gateway log* carries an id. The log also holds
    startup lines (`loaded provider plugin: openrouter`) that belong to no request, and text
    that is not a log record at all (a pydantic `UserWarning` on stderr). No correct
    implementation can satisfy it: stamping startup lines means inventing an id, the same
    defect as a well-formed traceparent that joins nothing. Rescoped to the window between the
    first and last identified line — full strength where request handling happens, which is
    where the defect it hunts lives — plus a floor of ≥2 identified lines so it cannot pass
    vacuously (before this change exactly one line carried an id).
  - **`test_a_valid_accounted_request_allocates_one_gateway_call_id` was retargeted, not
    weakened.** It patched the two former mint sites and asserted one call; the id is now
    minted once in middleware, so both patches observed zero. The claim — one allocation per
    request, and the response carries that id — is unchanged; only the patch target moved.
    Counts: test functions 46 → 46, assertions 194 → 194.
  - **The redundant `gateway_call_id=` interpolation in `session.py` is KEPT deliberately.**
    It now renders twice on that one line (once from the filter prefix, once in the message)
    and removing it looks like an obvious cleanup. It is not: two prior tests assert
    `call_id in record.getMessage()` — the MESSAGE, not the formatted line — and the prefix is
    added by the Formatter, so removing the interpolation breaks both.
  - **Middleware registration order is counter-intuitive and is commented as such.**
    `add_middleware` does `user_middleware.insert(0, ...)` and the stack wraps that list in
    reverse, so the LAST registration is the OUTERMOST. `CallIdMiddleware` is therefore added
    after the auth guard, so the guard's rejection lines are inside a bound scope. Verified by
    reading Starlette's source rather than from memory — the first attempt had it backwards.
  - Ladder counts: test functions 5 → 5, assertions 14 → 15, xfail markers 10 → 8.
