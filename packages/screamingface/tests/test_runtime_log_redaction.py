"""Structural prompt carriers never reach runtime.log (OME-1050, owner option A).

FEATURE: local runtime log hygiene. `runtime.log` is the process's entire stdout/stderr sink.
STORY: as a researcher debugging a run, I want the runtime log I paste into a bug report to
hold no prompt text that rode in on a url4 query, a litellm exception or a litellm debug curl.

SCOPE: three STRUCTURAL carriers only. Unmarked free text is out of scope by owner decision;
partial redaction of free text is unreliable (report_intake/classification/content.py).
"""

from __future__ import annotations

import logging
import os
import sys
import types
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

from screamingface._runtime import bootstrap, log_redaction, runtime_logging, server

PLANTED = "PLANTED-PROMPT-tell-me-the-launch-codes"

# One planted line per structural carrier, each with non-secret context that must survive.
CARRIERS: dict[str, tuple[str, str]] = {
    "url4-query": (
        f"GET 'http://127.0.0.1:9108/?q={PLANTED}&limit=1' failed: 500",
        "http://127.0.0.1:9108/?q=",
    ),
    "litellm-messages": (
        f"litellm.BadRequestError: upstream said no\nMessages: `[{{'content': '{PLANTED}'}}]`",
        "litellm.BadRequestError: upstream said no",
    ),
    "litellm-curl-body": (
        "POST Request Sent from LiteLLM:\ncurl -X POST \\\nhttps://openrouter.ai/api \\\n"
        f'-d \'{{"messages": [{{"content": "{PLANTED}"}}]}}\'',
        "curl -X POST",
    ),
}


def _print(text: str) -> None:
    print(text, flush=True)


def _stdlib_showwarning(
    message: Warning | str,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: object = None,
    line: str | None = None,
) -> None:
    # The stdlib default's behaviour: resolve sys.stderr at CALL time and write the warning.
    sys.stderr.write(warnings.formatwarning(message, category, filename, lineno, line))


def _warn(text: str) -> None:
    # WHY replace showwarning: pytest records warnings for its summary, so the stdlib path
    # into sys.stderr — the one production takes — is not live under pytest without this.
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.showwarning = _stdlib_showwarning
        warnings.warn(text, UserWarning, stacklevel=1)


def _unconfigured_logger(text: str) -> None:
    # WHY clear root's handlers HERE and not in a fixture: pytest's logging plugin installs its
    # capture handler on the root logger for the call phase, after fixtures run, and any root
    # handler stops `logging.lastResort` from firing. Production configures no root handler.
    root = logging.getLogger()
    saved = list(root.handlers)
    root.handlers.clear()
    try:
        logging.getLogger("some.third_party.library").warning(text)
    finally:
        root.handlers[:] = saved


def _traceback(text: str) -> None:
    try:
        raise RuntimeError(text)
    except RuntimeError as exc:
        sys.excepthook(RuntimeError, exc, exc.__traceback__)


PRODUCERS: dict[str, Callable[[str], None]] = {
    "print": _print,
    "warnings.warn": _warn,
    "unconfigured-logger": _unconfigured_logger,
    "traceback": _traceback,
}


@pytest.mark.parametrize("producer", PRODUCERS)
@pytest.mark.parametrize("carrier", CARRIERS)
def test_no_structural_carrier_reaches_the_runtime_log(
    tmp_path: Path, producer: str, carrier: str
) -> None:
    # INVARIANT (OME-1050): whatever the producer, a prompt riding in a structural carrier
    # never lands in runtime.log. Each producer is a distinct path into sys.stderr; only the
    # unconfigured logger ever creates a LogRecord, so the line-level sink is what covers
    # print, warnings and tracebacks.
    planted, context = CARRIERS[carrier]
    path = tmp_path / "runtime.log"

    with runtime_logging.capture_runtime_log(path, foreground=False):
        PRODUCERS[producer](planted)

    written = path.read_text()
    assert PLANTED not in written
    assert context in written, "redaction must keep the non-secret context"
    assert log_redaction.REDACTED in written


def test_the_factory_preserves_an_already_installed_one(tmp_path: Path) -> None:
    # INVARIANT: the factory WRAPS whatever is installed (aigateway installs its own token
    # redaction and correlation id through the same hook) and restores it on exit.
    seen: list[str] = []
    original = logging.getLogRecordFactory()

    def preinstalled(*args: object, **kwargs: object) -> logging.LogRecord:
        record = original(*args, **kwargs)
        record.correlation_id = "corr-1"
        seen.append("preinstalled")
        return record

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger = logging.getLogger("test.ome1050.factory")
    logger.addHandler(handler)
    logger.propagate = False
    logging.setLogRecordFactory(preinstalled)
    try:
        with runtime_logging.capture_runtime_log(tmp_path / "runtime.log", foreground=False):
            logger.warning("fetch %s failed", f"/?q={PLANTED}")
        assert logging.getLogRecordFactory() is preinstalled
    finally:
        logging.setLogRecordFactory(original)
        logger.removeHandler(handler)

    assert seen == ["preinstalled"]
    [record] = records
    assert getattr(record, "correlation_id", None) == "corr-1"
    # Redacted at the record, so EVERY handler sees the redacted text, not just RuntimeLog.
    assert record.getMessage() == f"fetch /?q={log_redaction.REDACTED} failed"


def test_the_factory_is_installed_once_when_nested() -> None:
    original = logging.getLogRecordFactory()
    with log_redaction.redacting_record_factory():
        outer = logging.getLogRecordFactory()
        with log_redaction.redacting_record_factory():
            assert logging.getLogRecordFactory() is outer
        assert logging.getLogRecordFactory() is outer
    assert logging.getLogRecordFactory() is original


def test_a_factory_installed_on_top_is_not_unwound_on_exit() -> None:
    # WHY: restoring the saved factory while someone else's wrapper sits on top would silently
    # drop theirs. Ours then stays in the chain, where it only ever redacts.
    original = logging.getLogRecordFactory()
    try:
        with log_redaction.redacting_record_factory():
            inner = logging.getLogRecordFactory()

            def on_top(*args: object, **kwargs: object) -> logging.LogRecord:
                return inner(*args, **kwargs)

            logging.setLogRecordFactory(on_top)
        assert logging.getLogRecordFactory() is on_top
    finally:
        logging.setLogRecordFactory(original)


def test_a_record_whose_message_cannot_render_is_left_for_logging_to_report() -> None:
    # Boundary: a malformed record keeps logging's own error reporting; the factory must not
    # raise while building it, nor rewrite it.
    with log_redaction.redacting_record_factory():
        factory = logging.getLogRecordFactory()
        bad = factory("x", logging.INFO, __file__, 1, "%d", ("not-a-number",), None)

    assert (bad.msg, bad.args) == ("%d", ("not-a-number",))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain line, nothing to hide", "plain line, nothing to hide"),
        ("GET /?top=10&q=abc&x=1", f"GET /?top=10&q={log_redaction.REDACTED}&x=1"),
        ("GET /?query=keep&top=3", "GET /?query=keep&top=3"),
        # Whitespace OUTSIDE quotes is the URL's end (review round 1, owner rule).
        ("GET /?q=abc HTTP/1.1", f"GET /?q={log_redaction.REDACTED} HTTP/1.1"),
        # A repr's closing quote reads as an unterminated quoted segment, so it fails closed to
        # the end of the line. Losing the trailing context beats leaking a quoted intent.
        ("fetch '/?q=abc' failed", f"fetch '/?q={log_redaction.REDACTED}"),
        ("Messages: `[1]`", f"Messages: {log_redaction.REDACTED}"),
        ("-d '{\"a\": 1}'", f"-d '{log_redaction.REDACTED}'"),
        ("rm-d 'x'", "rm-d 'x'"),
    ],
)
def test_redact_touches_only_the_structural_carriers(text: str, expected: str) -> None:
    assert log_redaction.redact(text) == expected


@pytest.mark.parametrize("current", ["DEBUG", "debug", "INFO", None])
def test_litellm_debug_logging_is_neutralised(current: str | None) -> None:
    # WHY set, never unset: litellm reads `os.getenv("LITELLM_LOG", "DEBUG")` at import, so an
    # absent variable IS debug. Mirrors request_hardening's strip of the per-request switch.
    environment = {} if current is None else {"LITELLM_LOG": current}

    bootstrap.neutralise_litellm_debug(environment)

    assert environment == {"LITELLM_LOG": "WARNING"}


def test_litellm_exception_messages_are_pinned_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = types.ModuleType("litellm")
    stub.redact_messages_in_exceptions = False  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", stub)

    bootstrap.pin_litellm_redaction()

    assert stub.redact_messages_in_exceptions is True  # type: ignore[attr-defined]


def test_the_runtime_boot_neutralises_litellm_before_any_app_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT: litellm binds its handler level at import, and the gateway import pulls it
    # in — so require_runtime_extra neutralises the environment before it imports any app.
    seen_at_import: list[str | None] = []

    def verify(source: object, modules: object) -> None:
        seen_at_import.append(os.environ.get("LITELLM_LOG"))

    monkeypatch.setenv("LITELLM_LOG", "DEBUG")
    monkeypatch.setattr(server, "_missing_runtime_modules", lambda names: ())
    monkeypatch.setattr(server, "activate", lambda source: None)
    monkeypatch.setattr(server, "verify_live_modules", verify)
    monkeypatch.setattr(server, "enable_local_providers", lambda environment: None)
    for name in ("aigateway", "scoreboard", "screamingface_engine", "url4", "uvicorn"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    server.require_runtime_extra()

    assert seen_at_import == ["WARNING"]


# --- review round 1 (PR #1206) -------------------------------------------------------------


class _UnprintableArg:
    def __str__(self) -> str:
        raise RuntimeError("this argument cannot be rendered")


@pytest.mark.parametrize(
    ("message", "args"),
    [
        # A mapping-style format with the key missing: getMessage raises KeyError.
        ("%(a)s", ({"b": 1},)),
        # An argument whose __str__ raises something other than TypeError/ValueError.
        ("value: %s", (_UnprintableArg(),)),
    ],
)
def test_a_record_that_cannot_render_never_raises_at_the_logging_call(
    message: str, args: tuple[object, ...], capsys: pytest.CaptureFixture[str]
) -> None:
    # INVARIANT: logging never raises from our factory. A record that cannot render must reach
    # logging's own "--- Logging error ---" path untouched, exactly as it would without us.
    records: list[logging.LogRecord] = []
    # WHY a Logger built directly, outside the manager: pytest's logging plugin attaches its
    # own capture handlers, whose handleError RAISES. That would mask the stdlib error path
    # this test pins. The global record factory still applies to an unmanaged Logger.
    logger = logging.Logger("test.ome1050.unrenderable")
    handler = logging.StreamHandler(sys.stderr)
    handler.emit = lambda record: (
        records.append(record),
        logging.StreamHandler.emit(handler, record),
    )  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.propagate = False
    with log_redaction.redacting_record_factory():
        logger.warning(message, *args)

    [record] = records
    assert record.msg == message
    assert "--- Logging error ---" in capsys.readouterr().err


# url4 renders a Text intent quoted (`render.py` `_quote`: single quotes, `\'` and `\\`
# escaped), so the prompt sits INSIDE quotes within the q= value — with spaces, `&` and `#`
# free to appear in it. The double-quoted twin covers a value quoted the other way.
QUOTED_INTENTS: dict[str, tuple[str, str]] = {
    "single-quoted": (
        f"GET /?q=(x)!'summarize my {PLANTED} memo & keep # it' HTTP/1.1",
        "GET /?q=",
    ),
    "single-quoted-escaped": (
        f"GET /?q=(x)!'it\\'s {PLANTED} & more'&limit=1 HTTP/1.1",
        "&limit=1 HTTP/1.1",
    ),
    "double-quoted": (
        f'GET /?q=(x)!"summarize my {PLANTED} memo" HTTP/1.1',
        "HTTP/1.1",
    ),
    "inside-a-repr": (
        f"GET \"http://127.0.0.1:9108/?q=(x)!'summarize my {PLANTED} memo'\" failed",
        "http://127.0.0.1:9108/?q=",
    ),
    "unterminated": (
        f"GET /?q=(x)!'summarize my {PLANTED} memo",
        "GET /?q=",
    ),
}


@pytest.mark.parametrize("producer", PRODUCERS)
@pytest.mark.parametrize("intent", QUOTED_INTENTS)
def test_a_quoted_text_intent_never_reaches_the_runtime_log(
    tmp_path: Path, producer: str, intent: str
) -> None:
    # INVARIANT: the whole q= value is redacted, quoted segments included, up to the URL's
    # real end (`&`, `#` or whitespace OUTSIDE quotes, or the end of the line). An
    # unterminated quote fails closed to the end of the line.
    planted, context = QUOTED_INTENTS[intent]
    path = tmp_path / "runtime.log"

    with runtime_logging.capture_runtime_log(path, foreground=False):
        PRODUCERS[producer](planted)

    written = path.read_text()
    assert PLANTED not in written
    assert "memo" not in written
    assert context in written
