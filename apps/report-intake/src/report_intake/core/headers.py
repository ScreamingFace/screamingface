"""The general request-header allowlist.

An allowlist rather than a denylist, and named fields rather than a pattern: the failure mode of
a denylist is that the next header someone forwards is trusted by default, and this service's
whole identity story rests on which headers it will read.

INVARIANT: the mesh identity header is **not** here and must never be added. It is honoured only
after the peer check, it is named in exactly one module (`OME-1011`'s mesh identity adapter), and
a general reader that returns it is how a client-supplied copy reaches code that believes it.
The edge strips inbound copies, but the edge is one hop; this is the other half.
"""

from __future__ import annotations

from collections.abc import Mapping

ALLOWED_REQUEST_HEADERS = ("content-type", "idempotency-key")
"""Headers any caller may set and this service will read (spec §2.1's table, minus identity).

`Cf-Turnstile-Response` is deliberately absent: like the identity header it is read once, by the
one module that evaluates it (`OME-1011`), not by a general-purpose reader.
"""


def read_allowed(headers: Mapping[str, str]) -> dict[str, str]:
    """The allowlisted subset of ``headers``, keyed by lowercase name.

    Anything not named in :data:`ALLOWED_REQUEST_HEADERS` is dropped without comment — a caller
    sending an unknown header is not an error, it is simply not listened to.
    """
    lowered = {name.lower(): value for name, value in headers.items()}
    return {name: lowered[name] for name in ALLOWED_REQUEST_HEADERS if name in lowered}
