"""Every log line of a request carries that request's `gateway_call_id` (OME-938).

Before this, the id appeared on exactly ONE line — `plugins/taxonomy/session.py:135` — so an
operator holding an id from a response body could find the line announcing it and nothing about
what the call did. Dispatch, cache, retry and concurrency lines were all anonymous.

The two properties worth stating up front, because both are ways this can be built wrong in a
way no ordinary test would catch:

- **The injector WRAPS the existing record factory.** `install_provisioning_token_redaction`
  owns the single `logging.setLogRecordFactory` slot. Replacing it disables provisioning-token
  redaction — a security regression hiding inside an observability change. Asserted directly.
- **The id is bound in middleware, not in the taxonomy plugin.** The plugin is gated by
  `AIGW_TAXONOMY_ENABLED`, so minting there means disabling usage accounting silently deletes
  the only correlation mechanism.
"""

from __future__ import annotations

import logging

import pytest

from aigateway import logs
from aigateway.call_context import (
    call_scope,
    current_call_id,
    install_call_context_injection,
    new_gateway_call_id,
    record_call_id,
)
from aigateway.core.auth.log_filter import install_provisioning_token_redaction

CALL_ID = "call_" + "a" * 32
OTHER_ID = "call_" + "b" * 32

SECRET = "DEADBEEFDEADBEEFDEADBEEFDEADBEEF"
LEAKY_MESSAGE = f"upstream call headers X-Aigw-Provisioning-Token: {SECRET} done"
"""A message the redaction filter genuinely matches.

WHY the exact header spelling matters: `RedactProvisioningTokenFilter._PATTERN` keys on
`X-Aigw-Provisioning-Token` followed by `:`/`=`. A message merely *containing* a secret-looking
token does not match, so a security test written with one would assert the absence of a string
that was never going to be there — passing whether or not the factory was wrapped. Every
assertion below therefore also checks `[REDACTED]` is PRESENT, proving redaction actually ran.
"""


@pytest.fixture(autouse=True)
def _restore_log_record_factory():
    """Every test here mutates process-wide logging state; put it back afterwards.

    WHY autouse and not a helper: a leaked factory does not fail the test that leaked it, it
    fails an unrelated one later, and the traceback points at the innocent party.
    """
    original = logging.getLogRecordFactory()
    try:
        yield
    finally:
        logging.setLogRecordFactory(original)


def _record() -> logging.LogRecord:
    """A record built the way `logging` builds one — through the installed factory."""
    return logging.getLogRecordFactory()(
        "aigateway.test", logging.INFO, __file__, 1, "a message", (), None
    )


# --- the scope ---------------------------------------------------------------------------


def test_outside_a_request_there_is_no_call_id() -> None:
    assert current_call_id() is None


def test_the_scope_binds_and_restores() -> None:
    with call_scope(CALL_ID):
        assert current_call_id() == CALL_ID
    assert current_call_id() is None


def test_nested_scopes_do_not_leak() -> None:
    with call_scope(CALL_ID):
        with call_scope(OTHER_ID):
            assert current_call_id() == OTHER_ID
        assert current_call_id() == CALL_ID


def test_minted_ids_match_the_published_shape() -> None:
    """`call_<32 hex>` is asserted by `usage_accounting.schema.json` and by response bodies."""
    import re

    assert re.fullmatch(r"call_[0-9a-f]{32}", new_gateway_call_id())
    assert new_gateway_call_id() != new_gateway_call_id()


# --- the record factory ------------------------------------------------------------------


def test_a_record_created_inside_a_scope_carries_that_calls_id() -> None:
    install_call_context_injection()

    with call_scope(CALL_ID):
        record = _record()

    assert record_call_id(record) == CALL_ID


def test_a_record_created_outside_any_scope_carries_no_id() -> None:
    """Boot and shutdown lines must stay byte-identical — absent, not an empty string."""
    install_call_context_injection()

    record = _record()

    assert record_call_id(record) is None


def test_installing_twice_does_not_double_wrap() -> None:
    install_call_context_injection()
    once = logging.getLogRecordFactory()
    install_call_context_injection()

    assert logging.getLogRecordFactory() is once


def test_the_injector_preserves_provisioning_token_redaction() -> None:
    """THE security test: the injector must WRAP the redaction factory, never replace it.

    Redaction owns the single `setLogRecordFactory` slot. A replacement silently stops
    scrubbing provisioning tokens from log records while every observability assertion in this
    file keeps passing — the failure is invisible except here.
    """
    install_provisioning_token_redaction()
    install_call_context_injection()

    with call_scope(CALL_ID):
        record = logging.getLogRecordFactory()(
            "aigateway.test", logging.INFO, __file__, 1, LEAKY_MESSAGE, (), None
        )

    rendered = record.getMessage()
    assert "[REDACTED]" in rendered, (
        "redaction did not run at all — this test would pass vacuously without this line"
    )
    assert SECRET not in rendered, (
        "the call-context injector replaced the redaction factory instead of wrapping it — "
        "provisioning tokens are now reaching the log"
    )
    assert record_call_id(record) == CALL_ID, "wrapping must not cost the call id"


def test_redaction_installed_after_the_injector_also_survives() -> None:
    """Install order must not decide whether secrets leak.

    `main` installs redaction first, but a test harness, a sidecar or a future refactor may
    not. Both orders have to end with both behaviours.
    """
    install_call_context_injection()
    install_provisioning_token_redaction()

    with call_scope(CALL_ID):
        record = logging.getLogRecordFactory()(
            "aigateway.test", logging.INFO, __file__, 1, LEAKY_MESSAGE, (), None
        )

    rendered = record.getMessage()
    assert "[REDACTED]" in rendered, "redaction did not run at all"
    assert SECRET not in rendered
    assert record_call_id(record) == CALL_ID


# --- rendering ---------------------------------------------------------------------------


def test_the_formatter_renders_the_id_onto_the_line() -> None:
    """An attribute nobody prints is not correlation.

    `logs._FORMAT` is plain text, so setting an attribute on the record renders NOWHERE unless
    the format carries it — the same reason the engine has a `%(run_context)s` slot.
    """
    install_call_context_injection()
    formatter = logging.Formatter(logs._FORMAT, defaults={"call_context": ""})
    filt = logs.CallContextFilter()

    with call_scope(CALL_ID):
        record = _record()
    filt.filter(record)

    assert CALL_ID in formatter.format(record)


def test_a_line_outside_a_request_is_unchanged() -> None:
    install_call_context_injection()
    formatter = logging.Formatter(logs._FORMAT, defaults={"call_context": ""})
    filt = logs.CallContextFilter()

    record = _record()
    filt.filter(record)

    assert formatter.format(record) == "INFO:     aigateway.test a message"


def test_interleaved_installs_do_not_stack_the_factory_chain() -> None:
    """REGRESSION: two installers sharing one slot must not grow the chain without bound.

    Each installer wraps whatever factory it finds. When the guard checked only the OUTERMOST
    factory, each one saw the other's wrapper, concluded it had not run, and wrapped again — so
    every interleaved pair added two layers. `create_app` installs both, and the suite builds
    thousands of apps, so the chain grew until creating a single log record blew the stack:
    `RecursionError: maximum recursion depth exceeded` raised at fixture setup, nowhere near
    anything resembling logging. 85 failures and 435 errors, from a guard reading one level.

    50 rounds is far past the point the old code broke, and the assertion is on chain DEPTH
    rather than on "it did not raise" — a chain that grows slowly would still pass the latter
    today and fail in a longer suite tomorrow.
    """
    for _ in range(50):
        install_provisioning_token_redaction()
        install_call_context_injection()

    depth = 0
    factory: object = logging.getLogRecordFactory()
    while factory is not None and depth < 100:
        factory = getattr(factory, "__wrapped__", None)
        depth += 1

    assert depth <= 3, f"the factory chain grew to {depth} wrappers across 50 install rounds"

    with call_scope(CALL_ID):
        record = logging.getLogRecordFactory()(
            "aigateway.test", logging.INFO, __file__, 1, LEAKY_MESSAGE, (), None
        )
    assert record_call_id(record) == CALL_ID
    assert "[REDACTED]" in record.getMessage()
