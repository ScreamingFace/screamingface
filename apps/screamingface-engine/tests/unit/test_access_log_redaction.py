"""No request query reaches the Engine's access log (OME-1795, spec E10, owner decision 3).

FEATURE: hosted BYOM, Unit 3. A direct `/classify` call carries the caller's text in its query,
and so does every expression on `GET /?q=`, chat included. uvicorn writes the whole request
target of every request to `uvicorn.access`; the App's filter cuts it at the first `?` before any
handler formats the line.

WHY uvicorn's own pieces: the record is built from uvicorn 0.52.3's five access arguments, with the
target from its `get_path_with_query_string`, and formatted with its `AccessFormatter`, so the
test reads the line an operator would.

INVARIANT: the method, the path, the HTTP version and the status stay; nothing else changes, and
no other logger is touched.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from urllib.parse import quote

import pytest
from uvicorn.logging import AccessFormatter
from uvicorn.protocols.utils import get_path_with_query_string

from screamingface_engine.access_log import QueryRedactingFilter, install_access_log_filter
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from url4.wire.subrequest import encode_subrequest

_MARKER = "synthetic-marker-5c1d"
_ACCESS = "uvicorn.access"
_FORMAT = '%(client_addr)s - "%(request_line)s" %(status_code)s'


@pytest.fixture(autouse=True)
def _own_access_filters() -> Iterator[None]:
    """Each test starts with the access logger's filters as they were, and leaves them so."""
    logger = logging.getLogger(_ACCESS)
    saved = list(logger.filters)
    for existing in saved:
        logger.removeFilter(existing)
    try:
        yield
    finally:
        for current in list(logger.filters):
            logger.removeFilter(current)
        for existing in saved:
            logger.addFilter(existing)


def _record(path: str, query: bytes, *, name: str = _ACCESS) -> logging.LogRecord:
    target = get_path_with_query_string({"path": path, "query_string": query})  # type: ignore[arg-type]
    return logging.LogRecord(
        name,
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "GET", target, "1.1", 200),
        None,
    )


def _line(record: logging.LogRecord) -> str:
    """The access line after the logger's own filters, as uvicorn's formatter writes it."""
    assert logging.getLogger(record.name).filter(record)
    return AccessFormatter(_FORMAT, use_colors=False).format(record) + "\n" + record.getMessage()


def _context() -> str:
    return json.dumps({"model": "byom_x/classifier_v1", "input": f"secret {_MARKER} text"})


_DIRECT = encode_subrequest("/classify", _context(), "classify").partition("?")[2]
_NESTED = "q=" + quote(f"/classify({_MARKER})!classify", safe="")
_CHAT = "q=" + quote(f"/anthropic/claude-haiku-4-5('{_MARKER}')!'go'", safe="")

_TARGETS = {
    "direct-raw": ("/classify", _DIRECT.encode()),
    "direct-encoded": ("/classify", quote(_DIRECT, safe="=").encode()),
    "nested-raw": ("/", f"q=/classify({_MARKER})!classify".encode()),
    "nested-encoded": ("/", _NESTED.encode()),
    "chat-expression": ("/", _CHAT.encode()),
    "two-params": ("/", f"x=1&q={_MARKER}&y=2".encode()),
}


@pytest.mark.parametrize(("path", "query"), list(_TARGETS.values()), ids=list(_TARGETS))
def test_no_query_reaches_a_formatted_access_line(path: str, query: bytes) -> None:
    install_access_log_filter()

    line = _line(_record(path, query))

    assert _MARKER not in line
    assert "?" not in line
    assert f'"GET {path} HTTP/1.1" 200 OK' in line
    assert "10.0.0.1:5000" in line


def test_a_record_without_a_query_is_unchanged() -> None:
    install_access_log_filter()
    record = _record("/healthz", b"")
    args = record.args

    _line(record)

    assert record.args == args


def test_a_question_mark_inside_the_path_is_not_taken_for_the_query() -> None:
    """uvicorn percent-encodes the path, so the first literal `?` always starts the query."""
    install_access_log_filter()

    line = _line(_record("/files/what?.txt", f"q={_MARKER}".encode()))

    assert '"GET /files/what%3F.txt HTTP/1.1"' in line
    assert _MARKER not in line


def test_a_record_of_another_shape_or_logger_is_untouched() -> None:
    install_access_log_filter()
    other_shape = logging.LogRecord(
        _ACCESS, logging.INFO, __file__, 0, "note %s", (f"/x?q={_MARKER}",), None
    )
    websocket = _record("/ws", f"token={_MARKER}".encode(), name="uvicorn.error")
    engine = _record("/classify", f"q={_MARKER}".encode(), name="screamingface_engine.rest")

    for record in (other_shape, websocket, engine):
        assert logging.getLogger(record.name).filter(record)
        assert _MARKER in record.getMessage()


def test_creating_the_app_twice_installs_one_filter() -> None:
    create_app(Settings(jwt_secret="access-log-secret"))
    create_app(Settings(jwt_secret="access-log-secret"))

    filters = logging.getLogger(_ACCESS).filters
    assert sum(isinstance(f, QueryRedactingFilter) for f in filters) == 1
    assert not any(
        isinstance(f, QueryRedactingFilter) for f in logging.getLogger("uvicorn.error").filters
    )
