"""Keep request queries out of the App's access log (OME-1795, spec E10, owner decision 3).

FEATURE: hosted BYOM, Unit 3. A direct `/classify` call carries the caller's text in its query,
and so does every expression on `GET /?q=`, chat included. uvicorn writes the whole request target
of every request to the `uvicorn.access` logger; this filter cuts it at the first `?` before any
handler formats the line.

WHY a filter on the logger, not on a handler or a formatter: a logger's filters run once per
record before any of its handlers, so the record is redacted whatever handlers and formats the
host installs. uvicorn's `dictConfig` replaces the logger's handlers and keeps its filters.

WHY `create_app` installs it: every start path (the deployed App, local mode, any other ASGI
host) builds the App through it, and no worker or run process does, so a run's own logs keep
their full text.

INVARIANT: only the request target changes, and only on an access record. The method, the path,
the HTTP version and the status stay, so the line still says what was called and how it ended.

Stdlib only, like `logs.py`: this module stays a shared leaf for the layering gate.
"""

import logging

ACCESS_LOGGER = "uvicorn.access"

# uvicorn 0.52.3's access record: (client address, method, path with query, HTTP version, status).
_ACCESS_ARGS = 5
_TARGET = 2


class QueryRedactingFilter(logging.Filter):
    """Replace an access record's request target by its path, dropping the query."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if (
            isinstance(args, tuple)
            and len(args) == _ACCESS_ARGS
            and isinstance(target := args[_TARGET], str)
        ):
            # WHY the first `?`: uvicorn percent-encodes the path, so a `?` inside it is `%3F`
            # and the first literal `?` always starts the query.
            record.args = (*args[:_TARGET], target.partition("?")[0], *args[_TARGET + 1 :])
        return True


def install_access_log_filter() -> None:
    """Add the filter to the access logger once, however many Apps the process builds."""
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(existing, QueryRedactingFilter) for existing in logger.filters):
        logger.addFilter(QueryRedactingFilter())


__all__ = ["ACCESS_LOGGER", "QueryRedactingFilter", "install_access_log_filter"]
