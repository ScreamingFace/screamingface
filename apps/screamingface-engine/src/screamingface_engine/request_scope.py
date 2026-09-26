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

INVARIANT: a producer binds a scope BEFORE any handler executes. There are two producers, and
they live apart on purpose:

- the RUN producer is `runner.main.request_scope_from_env` (it raises the run mode's own
  `RunnerConfigError`, so it lives with it). `runner.main._seeded_world` hands it to
  `Url4Executor`, which binds it around the run;
- the SYNC producer is :func:`request_scope_from_headers` and :func:`trace_from_headers`, in
  this module. The node tier (`world.node_tier.tier`) and local mode's mount (`local`) bind both
  of these, plus the run-context log identity, through the ONE helper, :func:`bind_sync_request`
  (FX-6): the two callers must not drift onto binding these three carriers apart from one
  another.

Nothing may call a handler outside a bound scope: `current_scope()` raises rather than inventing
a default, because an anonymous, unprofiled, unseeded call still reaches aigateway and still
bills someone (AC5).
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from screamingface_engine import job_env
from screamingface_engine.cache_intent import parse_cache_control
from screamingface_engine.logs import run_scope
from screamingface_engine.trace_scope import run_trace_scope
from url4.streaming.interfaces import TraceContext
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

# FEATURE (OME-1381, Stage D of OME-1138): selector-less provider access. Engine ingress refuses a
# stated `X-Profile` instead of carrying it; the gateway is still the only interpreter of a legacy
# selector already on a queued run. ONE code and ONE message for every Engine surface, REST
# (RFC 9457 `code` member) and sync mount (url4 envelope) alike.
# INVARIANT: the message never names the requested value — it is neither echoed nor logged.
X_PROFILE_UNSUPPORTED = "x_profile_unsupported"
X_PROFILE_UNSUPPORTED_MESSAGE = (
    "the X-Profile header is no longer supported; send the request without it"
)


class RequestScopeError(RuntimeError):
    """Read of the request scope with nothing bound.

    A NAMED engine error, beside the engine's other top-level failures (`WorldConfigError`,
    `RetrievalPolicyError`), so a caller that forgets to bind a producer gets an explanation
    rather than a bare `LookupError` from the ContextVar.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestScope:
    """Everything about the caller that used to live on `_ModelEndpoint`.

    Frozen so it cannot be mutated in place and accidentally read by a concurrent sibling, and
    slotted so it carries exactly these fields and no hidden attribute a future contributor could
    stash state in.

    ``identity_headers`` is the caller's VERIFIED identity (canonical header name → value, see
    `job_env.IDENTITY_HEADER_ENV`). ``origin`` distinguishes the two producers — "run" for a
    child process booted from its environment, "sync" for a per-request handler (unit 3) — so
    metrics, logs and the cache key can name the surface without inferring it.

    WHY no ``traceparent`` field (FX-64): the trace has ONE carrier, `trace_scope`. A copy here let
    the connector read one carrier on the sync path and the other on the run path; a sync
    producer now binds `trace_scope` itself, from :func:`trace_from_headers`.

    ``deadline`` (04-review-fixes §2.1) is a :func:`time.monotonic` instant by which the
    request must have answered, or ``None`` when no request budget applies. The sync producer
    sets ``start + request_timeout_s``; the run producer sets ``None``.
    """

    identity_headers: Mapping[str, str] = field(default_factory=dict)
    profile: str | None = None
    answer_seed: int | None = None
    cache: CachePolicy = field(default_factory=CachePolicy)
    # INVARIANT (FX-66): NO default. A scope that does not name its surface would be counted,
    # logged and keyed as whichever surface the default named — so every producer states it.
    origin: Literal["sync", "run"]
    # WHY on the scope and not on the connector: the transport retry is the only place that can
    # tell whether one more attempt still fits the budget, and the wrapper that owns the budget
    # cannot see the retry. A retry the wrapper then cuts off is billed and useless (NT-H1).
    deadline: float | None = None

    def __post_init__(self) -> None:
        # INVARIANT (FX-65): the scope OWNS what it holds. `frozen` stops a write to the scope's
        # fields, not a write to the caller's dict or `CachePolicy` (a mutable pydantic model)
        # that the field still points at — so a producer's later edit would reach a handler
        # mid-request. A read-only copy of the identity and a copy of the policy close that.
        # WHY `object.__setattr__`: the dataclass is frozen, so this is its one sanctioned write.
        object.__setattr__(self, "identity_headers", MappingProxyType(dict(self.identity_headers)))
        object.__setattr__(self, "cache", self.cache.model_copy())
        # AIDEV-NOTE (item 6, B6 review): `cache` is a COPY, but still a MUTABLE pydantic model —
        # `model_copy()` is shallow, not frozen. It is shared by every model call the run's
        # fan-out makes (one `RequestScope` instance, read by every concurrent call under it), so
        # never mutate it in place; treat it as read-only and build a new `CachePolicy` instead.
        # Also: `copy.deepcopy(RequestScope)` is UNSUPPORTED — `identity_headers` is a
        # `MappingProxyType`, which `copy.deepcopy` cannot pickle/copy, so a caller reaching for
        # a defensive deep copy of the whole scope raises instead of protecting anything.


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


def request_scope_from_headers(
    headers: Mapping[str, str], *, deadline: float | None = None
) -> RequestScope:
    """Producer 2 (F2, AC6): the sync surface's caller state, read off the verified headers.

    ``headers`` must look up case-insensitively (contracts.md C1 forwards HTTP header names; the
    ASGI layer supplies a case-insensitive view). It is the header-carrier sibling of
    `runner.main.request_scope_from_env`: the two share every VALUE's representation (identity via
    `job_env.identity_from_*`, the cache policy via :func:`cache_intent.parse_cache_control`) and
    differ only in carrier and in ``origin`` — which is exactly the one field that names them.

    The identity is the EDGE-VERIFIED header (D4). A client-supplied ``X-User-Email`` never
    reaches this function: the App strips and re-sets it before forwarding, and the node tier is
    reachable only from the App (C2 trust boundary).

    ``deadline`` is the request's :func:`time.monotonic` budget end (§2.1), carried unchanged.

    Raises:
        AnswerSeedError: ``X-Answer-Seed`` is present but not an integer. The same refusal the
            child boot makes, for the same reason (OME-1038).
    """

    return RequestScope(
        identity_headers=job_env.identity_from_headers(headers),
        profile=_optional(headers.get(PROFILE_HEADER)),
        answer_seed=_optional_int(headers.get(ANSWER_SEED_HEADER)),
        cache=parse_cache_control(headers.get(CACHE_CONTROL_HEADER)) or CachePolicy(),
        origin="sync",
        deadline=deadline,
    )


def trace_from_headers(headers: Mapping[str, str]) -> TraceContext | None:
    """The sync request's trace, for the producer to bind with `trace_scope.run_trace_scope`.

    FEATURE (FX-64): the header-carrier half of the ONE trace carrier. A sync producer binds this
    beside its request scope, so the connector reads the trace from `trace_scope` on every path.

    INVARIANT: as strict as :func:`valid_traceparent` — a malformed, all-zero or absent header is
    ``None``, and ``None`` binds "no trace", so the outbound call omits the header rather than
    forwarding a value that joins nothing.

    # WHY the flags are not kept: `trace_scope` renders the bound trace with url4's own
    # `format_traceparent`, which always writes the sampled flag `01` — the same rendering the
    # run path (`lifecycle.run`) has always sent. This deliberately RE-EMITS the trace sampled,
    # whatever the inbound flag was: an inbound `...-00` traceparent comes back out `...-01`,
    # same trace id, so the sync surface and the ensemble path agree on one rendering rather
    # than the sync surface forwarding a caller's unsampled flag downstream.
    """
    valid = valid_traceparent(_optional(headers.get(TRACEPARENT_HEADER)))
    if valid is None:
        return None
    _version, trace_id, span_id, _flags = valid.split("-")
    return TraceContext(trace_id=trace_id, root_span_id=span_id)


def requests_selector(values: Iterable[str]) -> bool:
    """Whether any of a request's ``X-Profile`` values states a selector.

    INVARIANT: the same "blank is absence" rule the node applies (`_optional`), so an ingress and
    the node can never disagree about what counts as a selector. EVERY value is judged, not the
    first: a blank first value must not hide a named second one, which a first-value reader would
    drop without a word — the silent ignore Stage D exists to close.
    """
    return any(_optional(value) is not None for value in values)


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


@contextmanager
def bind_sync_request(
    headers: Mapping[str, str], *, deadline: float | None = None
) -> Iterator[RequestScope]:
    """Producer 2's ONE binding: the request scope, the trace, and the log identity, together.

    FEATURE (FX-6): the node tier (`world.node_tier.tier`) and local mode's in-process mount
    (`local._LocalNodeMount`) are its two callers. Both need the SAME three carriers bound for one
    sync request — this module's `request_scope` (F2), `trace_scope.run_trace_scope` (FX-64, the
    ONE trace carrier) and `logs.run_scope` (the run-context log identity) — and binding them
    apart risked one caller carrying the log identity the other did not: before this, local mode's
    mount bound the first two only, so its sync log lines carried no ``origin`` or trace id while
    the deployed tier's did. Both now bind all three, so a sync request's log lines read the same
    on either surface.

    ``deadline`` is forwarded to :func:`request_scope_from_headers` unchanged — the tier's request
    budget; local mode passes none, exactly as it did before this helper existed.

    Raises:
        AnswerSeedError: before anything binds (see `request_scope_from_headers`), so a caller
            maps it to its own 400 response outside this context manager.
    """
    bound = request_scope_from_headers(headers, deadline=deadline)
    trace = trace_from_headers(headers)
    with (
        request_scope(bound),
        run_trace_scope(trace),
        run_scope(None, None if trace is None else trace.trace_id, origin="sync"),
    ):
        yield bound


__all__ = [
    "ANSWER_SEED_HEADER",
    "CACHE_CONTROL_HEADER",
    "PROFILE_HEADER",
    "TRACEPARENT_HEADER",
    "X_PROFILE_UNSUPPORTED",
    "X_PROFILE_UNSUPPORTED_MESSAGE",
    "AnswerSeedError",
    "RequestScope",
    "RequestScopeError",
    "bind_sync_request",
    "current_scope",
    "request_scope",
    "request_scope_from_headers",
    "requests_selector",
    "trace_from_headers",
]
