"""The request's caller state, bound for the duration of one request so a stateless handler
can read it.

FEATURE (F2, prd/01): the connector used to keep identity headers, profile, cache policy and
answer seed as fields on the long-lived `_ModelEndpoint`. That is safe only while one process
serves one caller: a single `Url4Node` shared by two callers would let the first request's
identity leave on the second request's aigateway call. The request scope moves every one of
those values onto a `ContextVar`, so a handler reads the caller's state at call time and holds
none of it on `self`.

WHY a ContextVar rather than constructor arguments: this is the idiom the engine already uses
twice — `trace_scope.py` for the W3C trace and `logs.py` for the run's log identity — and
ContextVars are copied into every task created inside the bound region. That copy is what makes
spawned model calls inherit their parent request (AC4) and what keeps sibling requests isolated
(AC2), without the handler or the world carrying a per-request field.

INVARIANT: a producer binds a scope BEFORE any handler executes — the child run path from its
`job_env` (see `runner.main.request_scope_from_env`), the sync surface from verified headers.
Nothing may call a handler outside a bound scope: `current_scope()` raises rather than inventing
a default, because an anonymous, unprofiled, unseeded call still reaches aigateway and still
bills someone (AC5).
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

from screamingface_engine import job_env
from screamingface_engine.cache_intent import parse_cache_control
from url4.streaming.protocol import CachePolicy
from url4.streaming.trace import valid_traceparent

# The sync surface's forwarded header names (contracts.md C1). They live HERE, beside the only
# function that reads them, so the node tier cannot half-rename one. INVARIANT: these are HTTP
# header names, NOT the Job env names `job_env.IDENTITY_HEADER_ENV` maps to — the two carriers
# differ on purpose and are reconciled only by `identity_from_headers`/`identity_from_env`.
PROFILE_HEADER = "X-Profile"
ANSWER_SEED_HEADER = "X-Answer-Seed"
CACHE_CONTROL_HEADER = "Cache-Control"
TRACEPARENT_HEADER = "traceparent"


class RequestScopeError(RuntimeError):
    """Read of the request scope with nothing bound.

    A NAMED engine error, beside the engine's other top-level failures (`WorldConfigError`,
    `RetrievalPolicyError`), so a caller that forgets to bind a producer gets an explanation
    rather than a bare `LookupError` from the ContextVar.
    """


@dataclass(frozen=True, slots=True)
class RequestScope:
    """Everything about the caller that used to live on `_ModelEndpoint`.

    Frozen so it cannot be mutated in place and accidentally read by a concurrent sibling, and
    slotted so it carries exactly these fields and no hidden attribute a future contributor could
    stash state in.

    ``identity_headers`` is the caller's VERIFIED identity (canonical header name → value, see
    `job_env.IDENTITY_HEADER_ENV`). ``origin`` distinguishes the two producers — "run" for a
    child process booted from its environment, "sync" for a per-request handler (unit 3) — so
    metrics, logs and the cache key can name the surface without inferring it.
    """

    identity_headers: Mapping[str, str] = field(default_factory=dict)
    profile: str | None = None
    traceparent: str | None = None
    answer_seed: int | None = None
    cache: CachePolicy = field(default_factory=CachePolicy)
    origin: Literal["sync", "run"] = "run"


# INVARIANT: NO default. A permissive default would let an unbound read silently produce an
# anonymous, unprofiled, unseeded call — the failure mode AC5 exists to prevent.
_scope: contextvars.ContextVar[RequestScope] = contextvars.ContextVar(
    "screamingface_engine_request_scope"
)


class AnswerSeedError(ValueError):
    """The sync caller's ``X-Answer-Seed`` was present but not an integer.

    A NAMED refusal mirroring `runner.main.RunnerConfigError`'s seed error: a request that
    declared a sitting must not silently run without it (OME-1038), because the response would
    then claim a sitting it never had. The node tier maps this to 400 rather than inventing a
    default.
    """


def request_scope_from_headers(headers: Mapping[str, str]) -> RequestScope:
    """Producer 2 (F2, AC6): the sync surface's caller state, read off the verified headers.

    ``headers`` must look up case-insensitively (contracts.md C1 forwards HTTP header names; the
    ASGI layer supplies a case-insensitive view). It is the header-carrier sibling of
    `runner.main.request_scope_from_env`: the two share every VALUE's representation (identity via
    `job_env.identity_from_*`, the cache policy via :func:`cache_intent.parse_cache_control`) and
    differ only in carrier and in ``origin`` — which is exactly the one field that names them.

    The identity is the EDGE-VERIFIED header (D4). A client-supplied ``X-User-Email`` never
    reaches this function: the App strips and re-sets it before forwarding, and the node tier is
    reachable only from the App (C2 trust boundary).

    Raises:
        AnswerSeedError: ``X-Answer-Seed`` is present but not an integer. The same refusal the
            child boot makes, for the same reason (OME-1038).
    """

    return RequestScope(
        identity_headers=job_env.identity_from_headers(headers),
        profile=_optional(headers.get(PROFILE_HEADER)),
        traceparent=valid_traceparent(_optional(headers.get(TRACEPARENT_HEADER))),
        answer_seed=_optional_int(headers.get(ANSWER_SEED_HEADER)),
        cache=parse_cache_control(headers.get(CACHE_CONTROL_HEADER)) or CachePolicy(),
        origin="sync",
    )


def _optional(raw: str | None) -> str | None:
    """A present-but-blank header is absence, not an empty value."""
    return (raw or "").strip() or None


def _optional_int(raw: str | None) -> int | None:
    """A missing/blank ``X-Answer-Seed`` is None; a non-integer is a loud refusal."""
    text = _optional(raw)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise AnswerSeedError(f"{ANSWER_SEED_HEADER} must be an integer, got {raw!r}") from exc


def current_scope() -> RequestScope:
    """The caller state bound for this task.

    Raises:
        RequestScopeError: nothing is bound. A silent default would send an anonymous,
            unprofiled, unseeded aigateway call and bill someone (AC5).
    """

    try:
        return _scope.get()
    except LookupError as exc:
        raise RequestScopeError(
            "no request scope is bound: a producer must bind one before any handler executes"
        ) from exc


@contextmanager
def request_scope(scope: RequestScope) -> Iterator[RequestScope]:
    """Bind one request's caller state for the duration of a scope; restore on exit.

    ``reset`` in a `finally` is what stops an inner request from inheriting an outer one's
    identity in the same task, and what stops a finished request's state leaking to the next.
    """

    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


__all__ = [
    "ANSWER_SEED_HEADER",
    "CACHE_CONTROL_HEADER",
    "PROFILE_HEADER",
    "TRACEPARENT_HEADER",
    "AnswerSeedError",
    "RequestScope",
    "RequestScopeError",
    "current_scope",
    "request_scope",
    "request_scope_from_headers",
]
