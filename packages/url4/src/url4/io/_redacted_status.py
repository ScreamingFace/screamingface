"""A source fetch's ``httpx.HTTPStatusError`` with its URLs shown by ``display_url``.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1539``) — push security review.
STORY: as an operator I hand a run a pre-signed ``https://…?X-Amz-Signature=…`` source; a 4xx
or 5xx from it is reported, and chained, without its signature.
"""

from __future__ import annotations

import httpx

from url4.core.url_display import display_url

_STATUS_KINDS = {
    1: "Informational response",
    3: "Redirect response",
    4: "Client error",
    5: "Server error",
}


def redacted_status_error(exc: httpx.HTTPStatusError) -> httpx.HTTPStatusError:
    """``exc`` with httpx's text rebuilt around :func:`display_url` — same request and response.

    WHY: ``raise_for_status`` writes the full request URL (and any ``Location``) into the text,
    and the error is both quoted in the message and chained as its cause.
    """
    response = exc.response
    code = response.status_code
    kind = _STATUS_KINDS.get(code // 100, "Invalid status code")
    lines = [
        f"{kind} '{code} {response.reason_phrase}' for url '{display_url(str(exc.request.url))}'"
    ]
    if response.has_redirect_location:
        lines.append(f"Redirect location: '{display_url(response.headers['location'])}'")
    lines.append(
        f"For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/{code}"
    )
    redacted = httpx.HTTPStatusError("\n".join(lines), request=exc.request, response=response)
    return redacted.with_traceback(exc.__traceback__)


__all__ = ["redacted_status_error"]
