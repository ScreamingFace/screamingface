"""Every status this service can return, as one constructor each.

`problem.py` is the plumbing; this is the catalogue. The split exists so that "which statuses
can a client receive?" is answered by reading one mapping rather than by grepping for
`ProblemException(` — an SDK codes against spec §2.3's table, and a status that table does not
list is what turns "my retry stopped working" into a support question.

INVARIANT: no route constructs a `ProblemException` with an ad-hoc status. A new status means a
new constructor here and a new row in the spec, in that order.

`403` and `503` are the pair to read carefully. They are the two ways the bot gate can stop a
report and they are NOT interchangeable, which is the whole reason `403` exists: `403` means the
token was missing or rejected, so the client fetches a fresh one; `503` means siteverify could
not be reached or could not be believed, so nothing was stored and the client retries unchanged.
Collapsing them would make one of those two client behaviours wrong.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .problem import ProblemException

PROBLEM_CATALOGUE: Mapping[int, str] = MappingProxyType(
    {
        400: "Bad Request",
        403: "Forbidden",
        413: "Payload Too Large",
        422: "Unprocessable Content",
        429: "Too Many Requests",
        503: "Service Unavailable",
    }
)
"""Status → RFC 9457 ``title``, matching spec §2.3 as amended (plan §12).

WHY the titles are literals rather than ``http.HTTPStatus(...).phrase``: the phrase for 422
changed between the two interpreters this app is tested on — "Unprocessable Entity" on 3.12,
"Unprocessable Content" on 3.13 — so deriving them would make a client's error body depend on
which Python the pod happens to run.
"""


def _problem(status: int, detail: str, headers: dict[str, str] | None = None) -> ProblemException:
    """Build the exception for a catalogued status. Raises `KeyError` for an uncatalogued one,
    which is the point: the failure lands on the developer adding the status, not on a client
    receiving an undocumented one."""
    return ProblemException(status, PROBLEM_CATALOGUE[status], detail, headers=headers)


def malformed_body(detail: str) -> ProblemException:
    """400 — the bytes are not the JSON object this endpoint parses."""
    return _problem(400, detail)


def unsupported_schema(declared: str, supported: str) -> ProblemException:
    """400 — a report from a `schema` major this service does not implement.

    Deliberately not 422: a major version mismatch is not something the client can fix by
    correcting a field, so telling it "unprocessable content" invites a pointless retry loop
    over a body that will never be accepted by this build.
    """
    return _problem(
        400,
        f"report schema {declared!r} is not supported by this service, which speaks {supported!r}",
    )


def body_too_large(limit_bytes: int, size_bytes: int | None = None) -> ProblemException:
    """413 — over spec §2.4's total body cap.

    The detail always names the cap (spec §2.3), and names the actual size too whenever the
    request declared one; a chunked body is cut off before its total is known, and inventing a
    number there would be worse than omitting it.
    """
    cap = f"the limit is {limit_bytes} bytes ({limit_bytes // 1024} KiB)"
    if size_bytes is None:
        return _problem(413, f"report body is over the limit; {cap}")
    return _problem(413, f"report body is {size_bytes} bytes; {cap}")


def schema_violation(detail: str) -> ProblemException:
    """422 — the report parsed but does not satisfy spec §2.1, or breaks a structural cap."""
    return _problem(422, detail)


def content_rejected(detail: str) -> ProblemException:
    """422 — prompt-bearing content (spec §4). Raised by `OME-1007`'s classifier, never here."""
    return _problem(422, detail)


def bot_gate_required(detail: str) -> ProblemException:
    """403 — an anonymous caller presented no Turnstile token, or one that was rejected.

    The client's move is to obtain a FRESH token and retry once (spec §8); retrying the same one
    is pointless, which is why this is not the same status as an unevaluable gate.

    INVARIANT: ``detail`` never contains the token. It arrived on an unauthenticated request and
    goes back out on one, and a rejected token is still a token somebody else might replay.
    """
    return _problem(403, detail)


def bot_gate_unverifiable() -> ProblemException:
    """503 — the bot gate could not be evaluated, so nothing was stored (spec §2.3, §8).

    Siteverify was unreachable, too slow, answered something this service cannot read, or
    rejected OUR secret rather than the caller's token. In every one of those the caller did
    nothing wrong, so telling them `403` would send them to fetch a token that was never the
    problem. Same shape as :func:`storage_unavailable`: back off, retry unchanged, keep the
    report on disk.
    """
    return _problem(
        503,
        "the bot check could not be completed, so nothing was accepted; keep the report and "
        "retry the same request",
    )


def loopback_only(detail: str) -> ProblemException:
    """403 — a network caller reached a process running with the gate turned off.

    Only reachable in `auth_mode=disabled`, which is the local development posture and is bound
    to loopback for exactly this reason. It is not part of the contract an SDK codes against —
    no deployment a client talks to runs this mode — which is why it reuses the catalogued `403`
    rather than adding a status to spec §2.3's table.
    """
    return _problem(403, detail)


def rate_limited(retry_after_s: int) -> ProblemException:
    """429 — the anonymous rate limit. Raised by `OME-1011`.

    `Retry-After` is not optional: a 429 with no backoff hint is answered by an immediate
    retry, which is the behaviour the limit exists to stop.
    """
    return _problem(
        429,
        "too many reports from this caller; retry after the interval in the Retry-After header",
        headers={"Retry-After": str(retry_after_s)},
    )


def storage_unavailable() -> ProblemException:
    """503 — nothing was stored. Raised by `OME-1008`'s pipeline.

    This is the one status that tells a client to stop trusting the service with the report and
    write it to disk instead (spec §8), so the detail says so rather than being generic.
    """
    return _problem(
        503,
        "the report could not be stored, so nothing was accepted; keep the report and retry",
    )
