"""The run-lifecycle REST surface: mint a capability token, start a run, stop a run.

Implements the transactional-HTTP half of the screamingface-engine protocol
(spec §4/§5): a token binds the caller to one topic, ``GET /`` starts the run for
that topic (synchronously or async per RFC 7240 ``Prefer``), and ``DELETE /`` stops
it and purges its stream. The streaming half (the WebSocket the caller attaches to
observe the run) lives elsewhere; this module only schedules work onto it via
``JobRunner``/``EventConsumer`` and enforces that a subscriber is attached first.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol, runtime_checkable

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import FileResponse

from screamingface_engine import job_env, notices
from screamingface_engine.artifacts import ArtifactStore
from screamingface_engine.auth import (
    PROBLEM_MEDIA_TYPE,
    JwtCodec,
    ProblemException,
    VerifiedClaims,
    new_topic,
)
from screamingface_engine.config import Settings
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.rest.cache_header import parse_cache_control
from screamingface_engine.rest.cache_policy import resolve
from screamingface_engine.rest.interest import SubscriberGate
from screamingface_engine.rest.sessions import RunSessions
from url4.streaming.interfaces import (
    EventConsumer,
    JobAlreadyExists,
    JobRunnerAtCapacity,
)
from url4.streaming.protocol import CachePolicy, ResultEvent, TerminatedEvent
from url4.streaming.trace import valid_traceparent

router = APIRouter()

_logger = logging.getLogger(__name__)

_TERMINAL_PROBLEM: dict[str, tuple[int, str, str]] = {
    "failed": (502, "Bad Gateway", "the run failed"),
    "timed_out": (504, "Gateway Timeout", "the run exceeded its deadline"),
    "stopped": (409, "Conflict", "the run was stopped"),
}


def _default_clock() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _Deps:
    """The run-scheduling collaborators a route handler needs, resolved from app state."""

    stream: EventConsumer
    job_runner: IdentityAwareJobRunner
    interest: SubscriberGate
    sessions: RunSessions
    settings: Settings
    artifact_store: ArtifactStore | None = None


def _deps(request: Request) -> _Deps:
    """Resolve ``_Deps`` from app state, or raise 503 if no job runner is configured."""
    state = request.app.state
    job_runner = state.job_runner
    if job_runner is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="run scheduling is not configured (URL4_CLOUD_RUNNER)",
        )
    return _Deps(
        stream=state.stream,
        job_runner=job_runner,
        interest=state.interest,
        # `registry` and not `interest`: the subscriber gate is a DI seam tests replace with a
        # fixed answer, while the session state is the real registry the WS transport writes an
        # attach frame's declaration into. Reading the declaration off a substituted gate would
        # make the frame carrier disappear the moment a test pinned the 428 behaviour.
        sessions=state.registry,
        settings=state.settings,
        # Direct attribute, no getattr fallback: create_app always builds the store, so
        # its absence is a wiring bug that must fail loudly, not degrade to 404s.
        artifact_store=state.artifact_store,
    )


@dataclass(frozen=True)
class _Prefer:
    """The parsed RFC 7240 ``Prefer`` header for a start-run request."""

    respond_async: bool
    wait_s: float | None


def _parse_prefer(raw: str) -> _Prefer:
    """Parse an RFC 7240 ``Prefer`` header into ``respond-async``/``wait=<seconds>`` flags.

    Unknown tokens are ignored; a malformed ``wait`` value falls back to ``None`` (the
    default synchronous bound), it never raises.
    """
    respond_async = False
    wait_s: float | None = None
    for token in raw.split(","):
        name, _, value = token.partition("=")
        key = name.strip().lower()
        if key == "respond-async":
            respond_async = True
        elif key == "wait":
            wait_s = _as_float(value)
    return _Prefer(respond_async=respond_async, wait_s=wait_s)


def _as_float(value: str) -> float | None:
    """Best-effort ``float`` parse: returns ``None`` instead of raising on bad input."""
    try:
        return float(value.strip())
    except ValueError:
        return None


def _require_q(q: str | None) -> str:
    """Return the url4 expression, or raise 400 if the ``q`` query parameter is missing/empty."""
    if not q:
        raise ProblemException(
            status=400,
            title="Bad Request",
            detail="the url4 expression query parameter `q` is required",
        )
    return q


# INVARIANT: a run must never be scheduled before a subscriber is attached to its topic —
# otherwise the run's terminal frame could be produced with nothing observing the stream.
async def _require_subscriber(interest: SubscriberGate, topic: str) -> None:
    """Raise 428 unless a WebSocket subscriber is already attached to ``topic``."""
    if not await interest.has_subscriber(topic):
        raise ProblemException(
            status=428,
            title="Precondition Required",
            detail="attach a WebSocket to the topic before starting the run",
        )


async def _schedule(
    deps: _Deps,
    topic: str,
    url4: str,
    *,
    traceparent: str | None = None,
    profile: str | None = None,
    identity: Mapping[str, str] | None = None,
    cache: CachePolicy,
) -> None:
    """Schedule the run on the job runner, or raise 409 if one already exists for ``topic``.

    Topics are single-shot: both the pre-check and the runner's own ``JobAlreadyExists`` guard
    against a race collapse into the same 409 problem.

    ``cache`` is the run's RESOLVED cache policy — the one thing both carriers converged on, and
    required rather than optional so that "nobody decided" cannot reach this hop. It travels
    beside ``profile`` and ``identity`` because it is the same kind of value: per-RUN, captured at
    the REST edge, re-rendered onto the aigateway call by the Runner. It is deliberately NOT world
    config; a per-run value parked on the shared aigateway configuration would leak across runs.
    """
    if await deps.job_runner.exists(topic):
        raise ProblemException(status=409, title="Conflict", detail="a run already exists")
    try:
        await deps.job_runner.schedule(
            topic,
            url4,
            deps.settings.job_deadline_s,
            traceparent=traceparent,
            profile=profile,
            identity=identity,
            cache=cache,
        )
        # The expression itself is the caller's, and may carry prompts — its LENGTH is
        # enough to tell a large Evaluation from a smoke run when reading back a failure.
        _logger.info(
            "run scheduled topic=%s url4_chars=%d profile=%s cache=%s",
            topic,
            len(url4),
            profile,
            cache,
        )
    except JobAlreadyExists as exc:
        raise ProblemException(status=409, title="Conflict", detail="a run already exists") from exc
    except JobRunnerAtCapacity as exc:
        # WHY 503 and not 429: nothing about THIS caller or request was rate-limited — the
        # substrate is saturated, and an identical retry later succeeds. Which substrates can
        # saturate, and why retrying is safe, is `JobRunnerAtCapacity`'s own contract (the
        # shapes: one shared event loop, a queue-depth ceiling, a scheduler's exhausted quota)
        # — this handler maps, it does not restate; the port's docstring stays the one source.
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the runner is at capacity — retry shortly",
            headers={"Retry-After": "1"},
        ) from exc


def _accepted(topic: str) -> Response:
    """Build the 202 Accepted response, with ``Location``/``Link``/``Preference-Applied``."""
    location = f"/?topic={topic}"
    return Response(
        status_code=202,
        headers={
            "Location": location,
            "Preference-Applied": "respond-async",
            "Link": f'<{location}>; rel="self"',
        },
    )


async def _scan_terminal(
    stream: EventConsumer, topic: str
) -> tuple[TerminatedEvent, ResultEvent | None]:
    """Consume ``topic``'s stream from the start until its terminal frame, unbounded.

    Returns the ``TerminatedEvent`` plus the last ``ResultEvent`` seen, if any. Callers that
    need a time bound wrap this in ``_await_terminal``.
    """
    result: ResultEvent | None = None
    async for event in stream.subscribe(topic, from_sequence=None):
        if isinstance(event, ResultEvent):
            result = event
        elif isinstance(event, TerminatedEvent):
            return event, result
    # AIDEV-NOTE: unreachable in practice — EventConsumer streams always end in a terminal
    # frame (spec §5); this guards against a stream implementation that violates that.
    raise RuntimeError("stream ended before a terminal frame")  # pragma: no cover


async def _await_terminal(
    stream: EventConsumer, topic: str, bound_s: float
) -> tuple[TerminatedEvent, ResultEvent | None] | None:
    """Bound ``_scan_terminal`` by ``bound_s`` seconds; returns ``None`` on timeout."""
    try:
        return await asyncio.wait_for(_scan_terminal(stream, topic), timeout=bound_s)
    except TimeoutError:
        return None


def _result_response(result: ResultEvent | None, store: ArtifactStore | None = None) -> Response:
    """Build the 200 response body from the run's ``ResultEvent``, or an empty 200 if none.

    FEATURE: deliver large results in full (OME-892) — a result frame may carry an artifact
    reference instead of an inline body; this transactional GET path resolves it to the same
    complete bytes the streaming client would fetch from ``GET /artifacts/{id}``.
    """
    if result is None:
        return Response(status_code=200)
    artifact = result.data.artifact
    if artifact is not None:
        path = store.path_for(artifact.id) if store is not None else None
        if path is None:
            # WHY 404 and not an empty 200: the run DID produce a result; serving nothing as
            # success would be a quieter cousin of the truncation bug this feature removes.
            raise ProblemException(
                status=404,
                title="Result artifact unavailable",
                detail=f"the run's result was spilled to artifact {artifact.id!r}, which has "
                "already been fetched or swept",
            )
        return FileResponse(path, media_type=result.data.media_type or "application/json")
    return Response(
        content=result.data.body,
        media_type=result.data.media_type or "application/json",
        status_code=200,
    )


def _terminal_response(
    terminated: TerminatedEvent,
    result: ResultEvent | None,
    store: ArtifactStore | None = None,
) -> Response:
    """Map a terminal frame to its HTTP response: the Result body on success, else a problem."""
    status = terminated.data.status
    if status == "succeeded":
        return _result_response(result, store)
    # `.get` and not `[...]`: a terminal status added to the protocol but not mapped here would
    # otherwise surface as an unhandled KeyError — a bare 500 with a traceback, rather than a
    # response that still tells the caller the run ended and did not succeed.
    http_status, title, detail = _TERMINAL_PROBLEM.get(
        status,
        (502, "Bad Gateway", f"the run ended with an unhandled terminal status: {status}"),
    )
    raise ProblemException(status=http_status, title=title, detail=detail)


_OVERRIDE_WARNING = (
    "this request's Cache-Control header overrode the cache policy declared on the attach frame"
)


def _converge_cache(
    deps: _Deps, topic: str, cache_control: str | None, clock: Callable[[], datetime]
) -> CachePolicy:
    """The run's one cache policy, and a word to the client when stating it cost them theirs.

    Convergence happens BEFORE the run is scheduled, so the notice is queued ahead of any frame
    the run itself produces: a client reads "your declaration was overridden" and only then the
    run that ran under the other policy, rather than having to reinterpret what it already saw.

    The warning names both halves of the disagreement, in the same attribute vocabulary the
    re-attach warning uses, because the client's question is the same one either way — *what did I
    ask for, and what actually applies?*
    """
    resolution = resolve(parse_cache_control(cache_control), deps.sessions.cache_policy_for(topic))
    if resolution.overridden is not None:
        deps.sessions.notify(
            topic,
            notices.warn(
                topic,
                clock,
                _OVERRIDE_WARNING,
                {
                    "cache.declared": notices.rendered(resolution.overridden),
                    "cache.effective": notices.rendered(resolution.effective),
                },
            ),
        )
    return resolution.effective


@runtime_checkable
class _QueueAware(Protocol):
    """A job runner that can report its queue depth — the queue backend (OME-1090).

    The port has no such method; the queue runner widens it, and the notice is only for
    that backend, so the route checks structurally rather than importing the adapter.
    """

    async def queue_depth(self) -> int: ...


async def _notify_queue_position(deps: _Deps, topic: str, clock: Callable[[], datetime]) -> None:
    """Tell the attached client where its run sits in the queue, if the runner is
    queue-backed (OME-1090).

    The client is already attached while its run is queued, so the wait should be visible
    instead of silent. The notice travels the WS bridge's existing `add_notifier` path —
    no protocol change, no stream write — and is superseded once `StartedEvent` arrives.
    """
    if not isinstance(deps.job_runner, _QueueAware):
        return
    position = await deps.job_runner.queue_depth()
    deps.sessions.notify(
        topic,
        notices.info(
            topic,
            clock,
            f"the run is queued at position {position}",
            {"queue.position": position},
        ),
    )


async def _run_sync(deps: _Deps, topic: str, wait_s: float | None) -> Response:
    """Hold the request until the run's terminal frame, or 202-fall-back once the bound elapses.

    The wait is capped at ``settings.sync_max_wait_s`` regardless of a caller-supplied
    ``wait_s`` (RFC 7240 ``Prefer: wait=``), so a client can shorten but never lengthen it.
    """
    cap = deps.settings.sync_max_wait_s
    bound = cap if wait_s is None else min(wait_s, cap)
    outcome = await _await_terminal(deps.stream, topic, bound)
    if outcome is None:
        return _accepted(topic)
    return _terminal_response(outcome[0], outcome[1], deps.artifact_store)


@router.post(
    "/token",
    tags=["Token"],
    summary="Mint a capability token",
    description="Generate a fresh topic and return its HS256 capability JWT (spec §4). No auth.",
)
async def mint_token(request: Request) -> dict[str, str]:
    """Mint a fresh topic and its HS256 capability JWT. Unauthenticated (see route summary)."""
    settings: Settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", _default_clock)
    codec = JwtCodec(
        secret=settings.jwt_secret,
        iat_window_s=settings.iat_window_s,
        capability_lifetime_s=settings.capability_lifetime_s,
    )
    return {"token": codec.sign(new_topic(), clock())}


def _problem(description: str) -> dict[str, Any]:
    """Build an OpenAPI response entry for an RFC 9457 problem, for use in ``responses=``."""
    return {
        "description": description,
        "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
    }


_START_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "The run succeeded — the Result body."},
    202: {
        "description": "Accepted — async (Prefer: respond-async, or the sync bound elapsed).",
        "headers": {
            "Location": {"schema": {"type": "string"}, "description": "The run handle."},
            "Link": {"schema": {"type": "string"}, "description": "RFC 8288 self link to the run."},
            "Preference-Applied": {
                "schema": {"type": "string"},
                "description": "RFC 7240 applied preference.",
            },
        },
    },
    400: _problem("The url4 expression query parameter `q` is required."),
    409: _problem("A run already exists for this topic (single-shot)."),
    428: _problem("Attach a WebSocket to the topic before starting the run."),
    502: _problem("The run failed."),
    504: _problem("The run exceeded its 16 h deadline."),
}
_STOP_RESPONSES: dict[int | str, dict[str, Any]] = {
    204: {"description": "Stopped and the stream purged (idempotent)."},
    403: _problem("The capability token is not authorized for that topic."),
}


_PREFER_DESC = (
    "RFC 7240 preference. Omit → synchronous: hold until the terminal frame (bounded by "
    "SYNC_MAX_WAIT), return the Result body. `respond-async` → asynchronous: 202 + Location/Link "
    "now, Result on the WebSocket stream. `wait=<seconds>` caps the synchronous hold."
)


_CACHE_CONTROL_DESC = (
    "RFC 9111 request cache directives, scoped to this whole run — every leaf and every fan-out "
    "branch. Omit → the run participates in the gateway's response cache (the default). "
    "`no-store` / `no-cache` → it does not. `max-age=<seconds>` → participate under a freshness "
    "bound. `url4-use-cache` → participate, explicitly. Conflicting directives resolve to "
    "not participating; unknown or malformed ones are ignored — a cache directive never fails a "
    "run."
)


_START_DESC = (
    "Start the run for the token's topic (spec §5).\n\n"
    "Synchronous (default): hold until the terminal frame (bounded by ``SYNC_MAX_WAIT``) and "
    "return the Result body, or an RFC 9457 problem. Asynchronous (``Prefer: respond-async``, or "
    "once the sync bound elapses): return ``202`` + ``Location``/``Link``; the Result arrives on "
    "the WebSocket stream. ``Prefer: wait=<seconds>`` caps the synchronous hold.\n\n"
    "An inbound ``traceparent`` header, when strictly W3C-valid, is forwarded to the run so its "
    "trace is adopted downstream; absent or malformed, nothing is forwarded — a fresh trace is "
    'minted instead (W3C "restart" rule: garbage never propagates).\n\n'
    "The optional ``X-Profile`` header selects which of the resolved caller's stored aigateway "
    "credentials to route through; absent, the gateway's default profile applies.\n\n"
    "The caller's verified identity header (``X-User-Email``) is read off the inbound request and "
    "carried to the run, which renders it onto its aigateway calls. Envoy strips and re-injects it "
    "after re-verifying Cloudflare Access's assertion, so a client cannot forge it. Absent, the "
    "run carries no identity and an aigateway in header mode rejects it.\n\n"
    "The optional ``Cache-Control`` header declares whether this run may participate in the "
    "gateway's response cache. It is the standard field, so an intermediary may read and add to "
    "it; a malformed or unknown directive is ignored rather than refused, because a cache "
    "directive is a hint about cost and must never fail a run."
)


@router.get(
    "/",
    tags=["Execution"],
    summary="Start a url4 run",
    responses=_START_RESPONSES,
    description=_START_DESC,
)
async def start_run(
    request: Request,
    claims: VerifiedClaims,
    q: str | None = None,
    prefer: Annotated[str | None, Header(alias="Prefer", description=_PREFER_DESC)] = None,
    traceparent: Annotated[
        str | None,
        Header(alias="traceparent", description="W3C trace context to adopt for this run."),
    ] = None,
    x_profile: Annotated[
        str | None,
        Header(alias="X-Profile", description="Optional aigateway routing profile label."),
    ] = None,
    # DECLARED HERE, RESOLVED IN `_converge_cache`. The run's cache intent has two carriers — this
    # header and the WS attach frame — and the header wins when both speak. Reading it into a
    # policy is therefore not this handler's business alone: `cache_header.parse_cache_control`
    # turns the field into intent, and convergence reconciles it with the frame's declaration
    # before the run is scheduled. The parameter lands here so the ingress contract and its
    # OpenAPI documentation are one thing, not two.
    cache_control: Annotated[
        str | None,
        Header(alias="Cache-Control", description=_CACHE_CONTROL_DESC),
    ] = None,
) -> Response:
    """Require an attached subscriber, then schedule the run for the token's topic, forwarding
    the adopted traceparent and the caller's verified identity; hold for the terminal frame by
    default, or return ``202`` immediately under ``Prefer: respond-async``.

    ``claims: VerifiedClaims`` is a FastAPI dependency, so JWT verification runs before this
    body executes — no code path here touches the topic without an already-verified capability
    token.
    """
    deps = _deps(request)
    topic = str(claims["sub"])
    url4 = _require_q(q)
    await _require_subscriber(deps.interest, topic)
    inbound_traceparent = valid_traceparent(traceparent)
    # WHY read identity off `request` instead of declaring another `Header(...)` param: the mesh
    # gateway owns it, not the caller, so there is no client-facing contract for a signature to
    # document. `or None`: absent identity is None, the same "nothing to forward" every other
    # optional forwarded value uses — one representation rather than an empty mapping meaning it.
    identity = job_env.identity_from_headers(request.headers) or None
    clock = getattr(request.app.state, "clock", _default_clock)
    await _schedule(
        deps,
        topic,
        url4,
        traceparent=inbound_traceparent,
        profile=x_profile,
        identity=identity,
        cache=_converge_cache(deps, topic, cache_control, clock),
    )
    await _notify_queue_position(deps, topic, clock)
    pref = _parse_prefer(prefer or "")
    if pref.respond_async:
        return _accepted(topic)
    return await _run_sync(deps, topic, pref.wait_s)


@router.delete(
    "/",
    tags=["Execution"],
    summary="Stop a run and purge its stream",
    responses=_STOP_RESPONSES,
    description=(
        "Stop the Job for the token's topic and purge its stream (idempotent) → ``204`` (spec §5)."
    ),
)
async def stop_run(request: Request, claims: VerifiedClaims, topic: str | None = None) -> Response:
    """Stop the run for the token's topic and purge its stream; raise 403 on a topic mismatch."""
    deps = _deps(request)
    sub = str(claims["sub"])
    if topic is not None and topic != sub:
        raise ProblemException(
            status=403,
            title="Forbidden",
            detail="the capability token is not authorized for that topic",
        )
    _logger.info("run stop requested topic=%s", sub)
    await deps.job_runner.stop(sub)
    # WHY delete and not purge: this is the run's terminal teardown, and purging a broker-backed
    # stream empties it but leaves the stream object, its consumer state and its filestore
    # directory behind — one permanent stream per run, forever. `delete_stream` defaults to
    # `purge` for adapters with nothing broker-side to reclaim, so both modes stay correct.
    await deps.stream.delete_stream(sub)
    return Response(status_code=204)
