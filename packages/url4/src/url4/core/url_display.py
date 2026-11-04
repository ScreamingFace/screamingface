"""How a source URL is shown in a log line, a span or an error message (push security review).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY: as an operator I hand a run a pre-signed ``https://…?X-Amz-Signature=…`` source; the
run's logs and errors name it by scheme, host and path, never by its signature.

WHY in ``core``: the engine (``url4.dag``) may reach ``url4.io`` only through its port modules
(``test_layering``), so the helper cannot sit beside ``io._source_policy.redact_userinfo``.
Standard library only.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

UNPARSEABLE = "<unparseable url>"
"""What :func:`display_url` shows for text the standard library cannot split."""


def display_url(raw: str) -> str:
    """``raw`` for display: scheme, host, port and path kept; secrets replaced by fixed markers.

    INVARIANT: userinfo becomes ``***``, any query ``?<redacted>``, any fragment
    ``#<redacted>`` — none of their text survives. A relative or template target (``/f/$x?…``)
    is shown the same way. Never raises: text ``urlsplit`` refuses is :data:`UNPARSEABLE`.
    AIDEV-NOTE: display only. Never feed the result back into a fetch or an identity.
    """
    try:
        parts = urlsplit(raw)
    except ValueError:
        return UNPARSEABLE
    userinfo, at, host = parts.netloc.rpartition("@")
    netloc = f"***@{host}" if at else host
    shown = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    if parts.query:
        shown += "?<redacted>"
    if parts.fragment:
        shown += "#<redacted>"
    return shown


__all__ = ["UNPARSEABLE", "display_url"]
