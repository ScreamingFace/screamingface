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
import math
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, Response

from screamingface_engine import job_env, notices
from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.artifacts import ArtifactStore
from screamingface_engine.auth import (
    PROBLEM_MEDIA_TYPE,
    JwtCodec,
    ProblemException,
    VerifiedClaims,
    default_clock,
    new_topic,
)
from screamingface_engine.cache_intent import parse_cache_control
from screamingface_engine.client_provenance import parse_user_agent
from screamingface_engine.config import Settings
from screamingface_engine.error_text import (
    CONTROL_PLANE_TERMINAL_CODES,
    ENGINE_ERROR_CODES,
    public_message,
)
from screamingface_engine.ports import IdentityAwareJobRunner, ReplayAwareJobRunner
from screamingface_engine.rest.artifacts import artifact_response
from screamingface_engine.rest.cache_policy import resolve
from screamingface_engine.rest.interest import SubscriberGate
from screamingface_engine.rest.selector import X_PROFILE_PARAMETER, refuse_selector
from screamingface_engine.rest.sessions import RunSessions
from screamingface_engine.runner_queue import RunQueueUnavailable
from screamingface_engine.tracing.accept import AcceptSpan
from url4.streaming.interfaces import (
    EventConsumer,
    JobAlreadyExists,
    JobRunnerAtCapacity,
)
from url4.streaming.protocol import CachePolicy, ErrorInfo, ResultEvent, TerminatedEvent
from url4.streaming.trace import parse_traceparent, valid_traceparent

router = APIRouter()

_logger = logging.getLogger(__name__)

# WHY 5 and not the capacity path's constant 1: an unreachable broker is a reconnect or a
# failover in flight, which takes seconds — a client told to retry in 1 s spends its retries
# inside the outage. There is no drain estimate to derive a better value from.
# INVARIANT: every "broker down" 503 (unreadable queue tail, unavailable queue at schedule time)
# uses THIS value; the capacity 503 keeps its drain estimate.
QUEUE_UNAVAILABLE_RETRY_AFTER_S = 5

CACHE_REPLAY_HEADER = "X-SF-Cache-Replay"

_TERMINAL_PROBLEM: dict[str, tuple[int, str, str]] = {
    "failed": (502, "Bad Gateway", "the run failed"),
    "timed_out": (504, "Gateway Timeout", "the run exceeded its deadline"),
    "stopped": (409, "Conflict", "the run was stopped"),
}

_SCRUBBED_CODE = "internal_error"


def _sanitized_error(error: ErrorInfo | None) -> tuple[str | None, str | None, bool | None]:
    """Reduce a terminal frame's ``ErrorInfo`` to what may cross the HTTP boundary.

    Returns ``(code, message, permanent)``. ``permanent`` always survives: it is a bool, it
    cannot carry text, and it is the one field that tells the caller whether a retry can ever
    succeed. The other two pass TWO independent screens (OME-941, review round 2):

    1. **Authorship.** ``ErrorInfo`` is built by ``url4.streaming.lifecycle._error_info``, which
       takes ``code`` from ``getattr(exc, "code")`` and ``message`` from ``str(exc)`` of whatever
       exception ended the run — provider text verbatim for any provider-facing adapter. Only a
       code in :data:`ENGINE_ERROR_CODES` vouches for its message's author, and that set is
       reserved engine-wide: ``world/connector.py::_raise_for_status`` refuses to mint one of
       those codes from an upstream response body, so an upstream cannot borrow the vouching.
       One shared set, not a second copy that would be free to drift.
    2. **Content, regardless of authorship.** Even a vouched message goes through the same
       :func:`public_message` the benchmark result contract uses: capped, flattened to one line,
       and withheld outright if it looks like an internal path, a traceback or a credential.
       An engine-authored message is not automatically a *bounded* one — ``malformed_source``
       embeds ``{token!r}`` of the caller's expression with no limit of its own.

    A code in :data:`CONTROL_PLANE_TERMINAL_CODES` (the supervisor's own ``cancelled``,
    ``queue_expired``, ``deadline_exceeded``, ``spawn_failed``) is reported as itself, with its
    message withheld.

    An unvouched or withheld message yields ``None``, and the caller falls back to the fixed
    table detail for the status. NOTE that ``_SCRUBBED_CODE`` is the genuine ``internal_error``
    code, not a distinct sentinel: a withheld body is therefore INDISTINGUISHABLE from a real
    internal failure. That is deliberate — telling a caller "there is a code here we are not
    showing you" is itself a signal — but it does mean the body is not self-describing.
    """
    if error is None:
        return None, None, None
    if error.code in ENGINE_ERROR_CODES:
        return error.code, public_message(error.message, default=""), error.permanent
    # The control plane's own terminal reason keeps its code — a cancelled or expired run is not
    # an engine fault — but, like every unvouched code, never its message (`spawn_failed` carries
    # `str(exc)`). Anything else is scrubbed to `internal_error`.
    code = error.code if error.code in CONTROL_PLANE_TERMINAL_CODES else _SCRUBBED_CODE
    return code, None, error.permanent


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


def _parse_answer_seed(raw: str | None) -> int | None:
    """Read the caller's declared answer seed, or raise 400 on a non-integer (OME-1038).

    Caller input, so refused at the edge — a run silently scheduled without its declared
    seed would publish a score claiming a sitting it never had. Any integer is legal:
    aigateway's ``seed`` is an arbitrary-integer sampling control (OME-585).
    """
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        raise ProblemException(
            status=400,
            title="Bad Request",
            detail="the X-Answer-Seed header must be an integer",
        ) from None


def _parse_replay_grant(request: Request) -> str | None:
    """Read the caller's opaque cache-version replay grant off the start request (E14, RP-D2).

    INVARIANT: the value is opaque. It is neither stripped nor decoded here — the gateway is the
    only party that verifies it. Every refusal happens at the edge, before anything is scheduled:
    a replay must never become a live run in silence.
    """
    values = [v for v in request.headers.getlist(CACHE_REPLAY_HEADER) if v.strip()]
    if not values:
        return None
    if len(values) > 1:
        raise ProblemException(
            status=400,
            title="Bad Request",
            detail="send one X-SF-Cache-Replay header",
            code="replay_grant_ambiguous",
        )
    value = values[0]
    if len(value.encode("utf-8")) > job_env.MAX_REPLAY_GRANT_BYTES:
        raise ProblemException(
            status=431,
            title="Request Header Fields Too Large",
            detail="the X-SF-Cache-Replay header exceeds 2048 bytes",
            code="replay_grant_too_large",
        )
    return value


def _checked_replay_grant(request: Request, deps: _Deps) -> str | None:
    """The request's replay grant, refused (503) when this Engine cannot replay.

    INVARIANT: the refusal comes BEFORE `_refuse_existing` and before any hold.
    """
    grant = _parse_replay_grant(request)
    if grant is not None:
        _replay_runner(deps)
    return grant


def _replay_runner(deps: _Deps) -> ReplayAwareJobRunner:
    """The job runner as a replay-aware one, or a 503 when this Engine's runner cannot carry a
    grant."""
    if isinstance(deps.job_runner, ReplayAwareJobRunner):
        return deps.job_runner
    raise ProblemException(
        status=503,
        title="Service Unavailable",
        detail="this Engine's runner cannot carry a cache-version replay",
        code="replay_unsupported",
    )


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


async def _refuse_existing(deps: _Deps, topic: str) -> None:
    """Raise 409 if a run already exists for ``topic`` (503 if that cannot be read).

    WHY a step of its own, BEFORE a sync request's hold (PRD 02 SY-D5): the hold is an audience
    transition, and the orphan reaper listens to those. A duplicate request that held the topic
    for a moment would disarm and re-arm the reaper of the run already there — resetting the
    grace of a run nobody is watching.
    """
    try:
        already_exists = await deps.job_runner.exists(topic)
    except QueueReadError:
        # V-3: an unreadable queue tail is UNKNOWN, and a 409 would assert — definitively,
        # in a form clients do not retry — that a run exists for a topic that may be brand
        # new. 503 says "this server could not read the queue; retry": honest, retryable,
        # and no state change either way.
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the run queue could not be read; retry",
            headers={"Retry-After": str(QUEUE_UNAVAILABLE_RETRY_AFTER_S)},
        ) from None
    if already_exists:
        raise ProblemException(status=409, title="Conflict", detail="a run already exists")


async def _schedule(
    deps: _Deps,
    topic: str,
    url4: str,
    *,
    traceparent: str | None = None,
    identity: Mapping[str, str] | None = None,
    cache: CachePolicy,
    answer_seed: int | None = None,
    client_version: str | None = None,
    shape: job_env.RunShape = "expression",
    deadline_s: int | None = None,
    replay_grant: str | None = None,
) -> None:
    """Schedule the run on the job runner; raise 409 if the runner reports it already exists.

    Topics are single-shot: `_refuse_existing` (the pre-check, before any hold) and the runner's
    own ``JobAlreadyExists`` guard against a race collapse into the same 409 problem.

    ``cache`` is the run's RESOLVED cache policy — the one thing both carriers converged on, and
    required rather than optional so that "nobody decided" cannot reach this hop. It travels
    beside ``identity`` because it is the same kind of value: per-RUN, captured at the REST edge,
    re-rendered onto the aigateway call by the Runner. It is deliberately NOT world config; a
    per-run value parked on the shared aigateway configuration would leak across runs.

    INVARIANT (OME-1381): both scheduling ingresses refuse a stated ``X-Profile`` before this hop,
    and the port cannot represent a selector, so every run this Engine schedules is selector-less.
    """
    try:
        deadline = deps.settings.job_deadline_s if deadline_s is None else deadline_s
        # WHY the plain call when there is no grant: a runner that is not replay-aware (the test
        # fakes) must keep working for every plain run. The grant is never logged.
        if replay_grant is None:
            await deps.job_runner.schedule(
                topic,
                url4,
                deadline,
                traceparent=traceparent,
                identity=identity,
                cache=cache,
                answer_seed=answer_seed,
                client_version=client_version,
                shape=shape,
            )
        else:
            await _replay_runner(deps).schedule(
                topic,
                url4,
                deadline,
                traceparent=traceparent,
                identity=identity,
                cache=cache,
                answer_seed=answer_seed,
                client_version=client_version,
                shape=shape,
                replay_grant=replay_grant,
            )
        # The expression itself is the caller's, and may carry prompts — its LENGTH is
        # enough to tell a large Evaluation from a smoke run when reading back a failure.
        _logger.info(
            "run scheduled topic=%s url4_chars=%d cache=%s",
            topic,
            len(url4),
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
        #
        # WHY a derived `Retry-After` (OME-1091): the queue-backed runner attaches its drain
        # estimate — how long until the queue has room, from depth and observed throughput — so a
        # client told to retry in 1 second when the true wait is minutes does not retry into a
        # wall. A runner with no estimate (the in-process and k8s ones) keeps the constant 1.
        retry_after = exc.retry_after_s
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the runner is at capacity — retry shortly",
            # CEIL at the boundary, not trust in the producer: `Retry-After` is
            # delta-seconds per RFC 7231 — a non-negative decimal INTEGER. The port
            # types the estimate as `int | None` and today's only producer ceils, but
            # the header is where the value becomes protocol, so the boundary renders
            # ANY future adapter's fractional estimate as a valid integer — rounding
            # UP, so a caller is never told to retry sooner than the estimate.
            headers={
                "Retry-After": str(math.ceil(retry_after)) if retry_after is not None else "1"
            },
        ) from exc
    except RunQueueUnavailable as exc:
        # FEATURE: an honest, retryable answer when the run queue is down (OME-948 R5's queue
        # analog, under OME-1086). Before this branch the broker's error escaped as a naked
        # plain-text 500. Nothing was queued and the reservation is already released, so an
        # identical retry is safe. The detail is generic: no broker vocabulary for the client.
        _logger.warning(
            "run not scheduled topic=%s: the run queue is unavailable", topic, exc_info=True
        )
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the run queue is unavailable — retry shortly",
            headers={"Retry-After": str(QUEUE_UNAVAILABLE_RETRY_AFTER_S)},
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


async def _result_response(
    result: ResultEvent | None, store: ArtifactStore | None = None
) -> Response:
    """Build the 200 response body from the run's ``ResultEvent``, or an empty 200 if none.

    FEATURE: deliver large results in full (OME-892) — a result frame may carry an artifact
    reference instead of an inline body; this transactional GET path resolves it to the same
    complete bytes the streaming client would fetch from ``GET /artifacts/{id}``.
    """
    if result is None:
        return Response(status_code=200)
    artifact = result.data.artifact
    if artifact is not None:
        media_type = result.data.media_type or "application/json"
        response = (
            await artifact_response(store, artifact.id, media_type) if store is not None else None
        )
        if response is None:
            # WHY 404 and not an empty 200: the run DID produce a result; serving nothing as
            # success would be a quieter cousin of the truncation bug this feature removes.
            raise ProblemException(
                status=404,
                title="Result artifact unavailable",
                detail=f"the run's result was spilled to artifact {artifact.id!r}, which has "
                "already been fetched or swept",
            )
        return response
    return Response(
        content=result.data.body,
        media_type=result.data.media_type or "application/json",
        status_code=200,
    )


async def _terminal_response(
    terminated: TerminatedEvent,
    result: ResultEvent | None,
    store: ArtifactStore | None = None,
) -> Response:
    """Map a terminal frame to its HTTP response: the Result body on success, else a problem."""
    status = terminated.data.status
    if status == "succeeded":
        return await _result_response(result, store)
    # `.get` and not `[...]`: a terminal status added to the protocol but not mapped here would
    # otherwise surface as an unhandled KeyError — a bare 500 with a traceback, rather than a
    # response that still tells the caller the run ended and did not succeed.
    http_status, title, detail = _TERMINAL_PROBLEM.get(
        status,
        (502, "Bad Gateway", f"the run ended with an unhandled terminal status: {status}"),
    )
    # OME-941: the frame's own diagnosis, sanitized, plus the run's trace id. Without these a
    # synchronous caller reads "the run failed" and has nothing to search a trace store with,
    # while the stream that held the answer is purged moments later.
    code, message, permanent = _sanitized_error(terminated.data.error)
    raise ProblemException(
        status=http_status,
        title=title,
        detail=message or detail,
        code=code,
        permanent=permanent,
        # `parse_traceparent` is the validator, not just a parser: a malformed or all-zero
        # traceparent yields None, so the member is absent rather than junk a caller would paste
        # into a trace search. The TOPIC is never rendered here — it is a bearer capability.
        trace_id=parse_traceparent(terminated.traceparent),
    )


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


_DISCONNECT_POLL_S = 0.5
"""How often a sync wait checks that its caller is still connected (PRD 02 §4: the hold is
released within 1 s of a disconnect)."""


async def _until_disconnected(is_disconnected: Callable[[], Awaitable[bool]]) -> None:
    while not await is_disconnected():
        await asyncio.sleep(_DISCONNECT_POLL_S)


WAIT_GONE = object()
"""`wait_terminal_or_gone`'s answer when the caller disconnected first."""


async def wait_terminal_or_gone(
    stream: EventConsumer,
    topic: str,
    bound_s: float,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> tuple[TerminatedEvent, ResultEvent | None] | None | object:
    """Race the run's terminal frame (bounded by `bound_s`) against the caller leaving.

    The terminal frame and its result; ``None`` when the bound passed first; ``WAIT_GONE`` when
    the caller disconnected first. Both tasks are cancelled and reaped on every exit. Shared by
    the sync `GET /?q=` and the mount calls, which differ only in what they do with the answer.
    """
    wait = asyncio.ensure_future(_await_terminal(stream, topic, bound_s))
    gone = asyncio.ensure_future(_until_disconnected(is_disconnected))
    try:
        await asyncio.wait({wait, gone}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (wait, gone):
            task.cancel()
        await asyncio.gather(wait, gone, return_exceptions=True)
    if wait.cancelled():
        return WAIT_GONE
    return wait.result()


async def _run_sync(
    deps: _Deps,
    topic: str,
    wait_s: float | None,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> Response:
    """Hold the request until the run's terminal frame, or 202-fall-back once the bound elapses
    — or stop waiting when the caller disconnects.

    The wait is capped at ``settings.sync_max_wait_s`` regardless of a caller-supplied
    ``wait_s`` (RFC 7240 ``Prefer: wait=``), so a client can shorten but never lengthen it.

    WHY watch the connection: the caller's hold keeps the run's audience alive, so a caller
    that is gone must release it promptly, or the orphan reaper would wait the full bound
    before its grace even starts. The run itself is not stopped: the token can still attach.
    """
    cap = deps.settings.sync_max_wait_s
    bound = cap if wait_s is None else min(wait_s, cap)
    outcome = await wait_terminal_or_gone(deps.stream, topic, bound, is_disconnected)
    if outcome is None or outcome is WAIT_GONE:
        # The bound passed (the client may attach a WebSocket) — or the caller is gone and
        # nobody reads this response.
        return _accepted(topic)
    terminated, result = outcome  # type: ignore[misc]
    return await _terminal_response(terminated, result, deps.artifact_store)


@router.post(
    "/token",
    tags=["Token"],
    summary="Mint a capability token",
    description="Generate a fresh topic and return its HS256 capability JWT (spec §4). No auth.",
)
async def mint_token(request: Request) -> dict[str, str]:
    """Mint a fresh topic and its HS256 capability JWT. Unauthenticated (see route summary)."""
    settings: Settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", default_clock)
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
    400: _problem(
        "The url4 expression query parameter `q` is required, or the request states the "
        "unsupported `X-Profile` header (`code: x_profile_unsupported`), or states more than "
        "one `X-SF-Cache-Replay` header (`code: replay_grant_ambiguous`)."
    ),
    409: _problem("A run already exists for this topic (single-shot)."),
    428: _problem("Attach a WebSocket to the topic before starting the run."),
    431: _problem(
        "The X-SF-Cache-Replay header exceeds 2048 bytes (`code: replay_grant_too_large`)."
    ),
    502: _problem("The run failed."),
    503: _problem(
        "This Engine's runner cannot carry a cache-version replay (`code: replay_unsupported`), "
        "or the runner is at capacity."
    ),
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
    "``X-Profile`` is no longer supported: a request that states one (any nonblank value) is "
    "refused with ``400`` and ``code: x_profile_unsupported`` before anything is scheduled. "
    "Absent or blank, the run uses the caller's provider access.\n\n"
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
    # Documents the refusal in OpenAPI; `refuse_selector` below is what decides.
    _x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None,
    x_answer_seed: Annotated[
        str | None,
        Header(
            alias="X-Answer-Seed",
            description="Optional integer answer seed: stamped as the `seed` param on every "
            "answer call the run makes (calls pinning their own seed win), so N seeded runs "
            "are N labelled samples and a re-run with the same seed replays the same sitting. "
            "Absent, the run's requests are byte-identical to an unseeded run's.",
        ),
    ] = None,
    # Documents the header in OpenAPI; `_parse_replay_grant` reads it off the request.
    _x_sf_cache_replay: Annotated[
        str | None,
        Header(
            alias="X-SF-Cache-Replay",
            description="Optional opaque cache-version replay grant (at most 2048 bytes). The "
            "Engine never reads its content; it carries it to AI Gateway on every chat call of "
            "the run.",
        ),
    ] = None,
    # DECLARED HERE, RESOLVED IN `_converge_cache`. The run's cache intent has two carriers — this
    # header and the WS attach frame — and the header wins when both speak. Reading it into a
    # policy is therefore not this handler's business alone: `cache_intent.parse_cache_control`
    # turns the field into intent, and convergence reconciles it with the frame's declaration
    # before the run is scheduled. The parameter lands here so the ingress contract and its
    # OpenAPI documentation are one thing, not two.
    cache_control: Annotated[
        str | None,
        Header(alias="Cache-Control", description=_CACHE_CONTROL_DESC),
    ] = None,
) -> Response:
    """Schedule the run for the token's topic, forwarding the adopted traceparent and the
    caller's verified identity; hold for the terminal frame by default, or return ``202``
    immediately under ``Prefer: respond-async``.

    A sync request needs no WebSocket: it holds the topic's audience itself while it waits
    (PRD 02). ``respond-async`` still requires an attached subscriber (428 otherwise).

    ``claims: VerifiedClaims`` is a FastAPI dependency, so JWT verification runs before this
    body executes — no code path here touches the topic without an already-verified capability
    token.
    """
    topic = str(claims["sub"])
    # FEATURE (OME-1218): the accept span covers validate + enqueue; the run is handed ITS id.
    accept = _open_accept(request, traceparent, topic)
    with _accepting(accept):
        refuse_selector(request.headers)
        deps = _deps(request)
        url4 = _require_q(q)
        pref = _parse_prefer(prefer or "")
        if pref.respond_async:
            # The client reads this run's frames on a WebSocket, so one must be attached first.
            await _require_subscriber(deps.interest, topic)
        inbound_traceparent = valid_traceparent(traceparent)
        # WHY read identity off `request` instead of declaring another `Header(...)` param: the
        # mesh gateway owns it, not the caller, so there is no client-facing contract for a
        # signature to document. `or None`: absent identity is None, the same "nothing to
        # forward" every other optional forwarded value uses — one representation rather than
        # an empty mapping meaning it.
        identity = job_env.identity_from_headers(request.headers) or None
        answer_seed = _parse_answer_seed(x_answer_seed)
        replay_grant = _checked_replay_grant(request, deps)
        clock = getattr(request.app.state, "clock", default_clock)
        client_version = (
            parse_user_agent(request.headers.get("User-Agent"))
            if len(request.headers.getlist("User-Agent")) == 1
            else None
        )
        await _refuse_existing(deps, topic)

        async def schedule() -> None:
            await _schedule(
                deps,
                topic,
                url4,
                # WHY the accept span's traceparent when one is open (owner decision, option
                # 1): `url4.run` becomes its child. With no sink, the inbound one, as before.
                traceparent=accept.traceparent if accept is not None else inbound_traceparent,
                identity=identity,
                cache=_converge_cache(deps, topic, cache_control, clock),
                answer_seed=answer_seed,
                client_version=client_version,
                replay_grant=replay_grant,
            )
            # INVARIANT (OME-1218 D2): the accept ends at ENQUEUE, before any sync hold — the
            # hold is not accept latency, and counting it would hide the queue-wait gap.
            if accept is not None:
                accept.scheduled()

        if pref.respond_async:
            await schedule()
            return _accepted(topic)
        # A sync caller is its own audience (PRD 02): the hold makes the gate pass and keeps
        # the reaper disarmed while it waits. ONE block covers gate, schedule and wait, so
        # every exit — a 503 from admission, the bound, a disconnect, an error — releases it.
        async with deps.sessions.hold_sync(topic):
            await _require_subscriber(deps.interest, topic)
            await schedule()
            return await _run_sync(deps, topic, pref.wait_s, request.is_disconnected)


def _open_accept(request: Request, traceparent: str | None, topic: str) -> AcceptSpan | None:
    """The submission's accept span, or ``None`` when the App exports no spans.

    INVARIANT (OME-1218 D4): no sink, no span — and then the inbound traceparent is forwarded
    untouched. A self-minted parent that nothing exports would dangle in every backend.
    `getattr`: an App assembled without `create_app` has no sink, which means "off".
    """
    sink = getattr(request.app.state, "span_sink", None)
    if sink is None:
        return None
    return AcceptSpan.open(sink, traceparent, topic=topic)


@contextmanager
def _accepting(accept: AcceptSpan | None) -> Iterator[None]:
    """End the accept span as REFUSED when the submission is answered with an error.

    Re-raises everything: this only records the outcome. A refusal after enqueue (the sync
    path's terminal problem) is a no-op — the span already ended as scheduled.
    """
    try:
        yield
    except ProblemException as exc:
        if accept is not None:
            accept.refused(exc.problem.status)
        raise
    except Exception:
        if accept is not None:
            accept.refused(500)
        raise


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
    try:
        await deps.job_runner.stop(sub)
    except QueueReadError:
        # V-2: an unreadable tail used to make `stop()` a SILENT no-op, and this handler
        # fell through to deleting the stream of a possibly-live run while answering 204.
        # The raise keeps the state unchanged and the answer honest: 503, retryable, and
        # the stream deletion below does not run.
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the run queue could not be read; retry",
            headers={"Retry-After": str(QUEUE_UNAVAILABLE_RETRY_AFTER_S)},
        ) from None
    # WHY delete_stream and not purge: this is the run's terminal teardown, and `delete_stream`
    # purges the subject on the shared events stream while KEEPING the terminal frame — the
    # evidence a run ended (the queue's dedupe gate, the runner's own admission bookkeeping, and
    # a repeated `DELETE /` all read that frame). Plain `purge` drops it too, and an empty
    # subject reads exactly like a run still queued — there is no per-run stream object left to
    # tell the two apart in a shared stream (erd.md §5).
    await deps.stream.delete_stream(sub)
    return Response(status_code=204)
