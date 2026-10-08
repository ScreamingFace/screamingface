"""Mount calls as direct runs (uniform executor PRD 04, contracts.md C2).

Every mount the declared world serves — an endpoint (`GET /<path>?q=(context)!intent`) or a data
route (`GET /<path>`) — is a FastAPI `GET` operation of its own, tagged `Mounts`, so it appears in
`/openapi.json` (ans:Q5). All of them run the SAME workflow as any other run: the App queues a
`shape=direct` run, holds its topic while it waits (the PRD 02 hold), and answers from the run's
terminal frame. A worker's child runs the ONE handler through `url4.peer.dispatch_direct` (D1).

The answers match the removed node tier's (MNT-C2, MNT-9): url4's error envelope
(`{"error": {"code", "message"}}`) and the status url4 would have given the code.

- identity: the verified `X-User-Email`, from the same source as `GET /?q=` — none → 403
- a stated `X-Profile` → 400 `x_profile_unsupported`, after identity and before every other
  answer below (OME-1381); a blank one is absence
- endpoint without `q` → 400 `missing_intent`; a bad `X-Answer-Seed` → 400 `malformed_header`
- target over 8 KiB → 414; admission refused → 503 `overloaded` + `Retry-After`
- bound (`min(Prefer wait, 30 s)`) passes → the run is STOPPED, then 504 (ans:Q9)
- the caller disconnects → the run is stopped (nobody can attach to a mount run)
- result ≤ 1 MiB → 200 inline; over it → 303 to a signed `/artifacts/{id}` (ans:Q10)
"""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import Response

from screamingface_engine import job_env
from screamingface_engine.artifacts.signing import signed_artifact_path
from screamingface_engine.auth.problem import ProblemException
from screamingface_engine.auth.token import new_topic
from screamingface_engine.request_scope import (
    CAPTURE_UNSUPPORTED,
    CAPTURE_UNSUPPORTED_MESSAGE,
    PROFILE_HEADER,
    X_PROFILE_UNSUPPORTED,
    X_PROFILE_UNSUPPORTED_MESSAGE,
    requests_selector,
    states_frozen_copy_mode,
)
from screamingface_engine.rest.routes import (
    WAIT_GONE,
    _converge_cache,
    _Deps,
    _deps,
    _parse_answer_seed,
    _parse_prefer,
    _result_response,
    _schedule,
    default_clock,
    wait_terminal_or_gone,
)
from screamingface_engine.rest.selector import X_PROFILE_PARAMETER
from screamingface_engine.runner_queue import RunQueueUnavailable
from screamingface_engine.world.serving import MountDescriptor, MountTable, mount_http_status
from screamingface_engine.world.wire import url4_error_body
from url4.streaming.protocol import ResultEvent, TerminatedEvent

logger = logging.getLogger(__name__)

MOUNT_TAG = "Mounts"
MOUNT_INLINE_LIMIT_BYTES = 1024 * 1024
"""The one inline limit for a mount response (ans:Q10): up to it, 200 with the body; over it,
303 to a signed artifact URL.

WHY this is not the run's frame cap: a result FRAME stays at 512 KiB
(`job_env.DEFAULT_RESULT_INLINE_CAP_BYTES`, OME-949) — a frame near 1 MiB exceeds the broker's
default `max_payload` once the envelope is added. A result between the two is spilled by the
child and served INLINE here, from the artifact store."""
ARTIFACT_URL_TTL_S = 600
"""How long a mount's signed artifact URL is valid (the removed node tier's value)."""
RUN_HEADER = "X-Url4-Run"
"""The response header naming the topic of the run that answered a mount call."""

_MOUNT_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "The handler's body, with the route's media type."},
    303: {"description": "The result is over 1 MiB: `Location` is a signed artifact URL."},
    400: {
        "description": "`missing_intent`, a malformed `q`, a bad `X-Answer-Seed`, or an "
        "unsupported `X-Profile` header (`x_profile_unsupported`)."
    },
    403: {"description": "No verified caller identity."},
    404: {"description": "The world has no such handler."},
    414: {"description": "The path plus query is longer than 8 KiB."},
    502: {"description": "The handler or its upstream failed."},
    503: {"description": "At capacity (`Retry-After`)."},
    504: {"description": "The bound passed; the run was stopped."},
}


def _envelope(status: int, code: str, message: str, headers: dict[str, str] | None = None):
    """url4's error envelope, byte for byte (`world.wire.url4_error_body`)."""
    return Response(
        content=url4_error_body(code, message),
        status_code=status,
        media_type="application/json",
        headers=headers,
    )


def install_mounts(app: FastAPI, derive: Callable[[], Awaitable[MountTable]]) -> None:
    """Derive the mount table at startup and register one route per mount.

    Startup, not construction: deriving builds the declared world (async). Requests are not
    served before startup completes, and a bad world or an F4 collision fails startup (C7).
    """

    async def _install() -> None:
        register_mounts(app, await derive())

    app.router.on_startup.append(_install)


def register_mounts(app: FastAPI, table: MountTable, *, require_identity: bool = True) -> None:
    """Register `table`'s mounts as `GET` routes and forget any cached OpenAPI schema (MC-D8).

    `require_identity=False` is LOCAL mode only (`serve --local`, loopback): it has no edge that
    verifies a caller, and a local mount call without `X-User-Email` has always been served.
    """
    for mount in table.mounts:
        # A url4 data key may be an exact TARGET (`/rows?limit=5`) or contain `{`, which FastAPI
        # would read as a path template: neither can be a route, so it is refused at startup.
        if "?" in mount.path or "{" in mount.path or "}" in mount.path:
            raise ValueError(f"mount path {mount.path!r} cannot be served as an HTTP route")
        app.router.add_api_route(
            mount.path,
            _handler_for(mount, require_identity=require_identity),
            methods=["GET"],
            tags=[MOUNT_TAG],
            summary=f"Call the {mount.kind} {mount.path}",
            description=(
                "One call to this world's "
                + (
                    "intent processor: `q=(context)!intent`."
                    if mount.kind == "endpoint"
                    else f"data route{f' ({mount.media_type})' if mount.media_type else ''}."
                )
                + " Runs as a direct run on the worker pool."
            ),
            responses=_MOUNT_RESPONSES,
            response_class=Response,
            name=f"mount:{mount.path}",
        )
        # AC14 parity: a mount speaks GET only, and a wrong method gets the NODE's answer —
        # url4's `method_not_allowed` envelope — not the framework's `{"detail": ...}` 405.
        app.router.add_api_route(
            mount.path,
            _method_not_allowed,
            methods=_OTHER_METHODS,
            include_in_schema=False,
            name=f"mount-method:{mount.path}",
        )
    app.state.mount_table = table
    # `/healthz` reports which config file the mounts came from (erd.md §2, R11).
    app.state.config_digest = table.config_digest
    # INVARIANT (MC-D8): a schema generated before the mounts existed must never be served again.
    app.openapi_schema = None


_OTHER_METHODS = ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


async def _method_not_allowed() -> Response:
    return _envelope(405, "method_not_allowed", "url4 nodes speak GET", {"Allow": "GET"})


def _handler_for(
    mount: MountDescriptor, *, require_identity: bool
) -> Callable[..., Awaitable[Response]]:
    async def call_mount(
        request: Request,
        q: Annotated[
            str | None,
            Query(description="`(context)!intent` for an endpoint; optional for a data route."),
        ] = None,
        prefer: Annotated[str | None, Header(alias="Prefer")] = None,
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
        # Documents the refusal in OpenAPI; `_validated` is what decides.
        _x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None,
        x_answer_seed: Annotated[str | None, Header(alias="X-Answer-Seed")] = None,
        cache_control: Annotated[str | None, Header(alias="Cache-Control")] = None,
    ) -> Response:
        return await _call(
            request,
            mount,
            require_identity=require_identity,
            q=q,
            prefer=prefer,
            traceparent=traceparent,
            answer_seed=x_answer_seed,
            cache_control=cache_control,
        )

    return call_mount


class _Refused(Exception):
    """A mount call answered before it reached the queue (or refused by admission)."""

    def __init__(self, response: Response) -> None:
        super().__init__(response.status_code)
        self.response = response


async def _call(request: Request, mount: MountDescriptor, **kwargs: Any) -> Response:
    """One mount call, counted by path and status (`screamingface_engine_mount_calls_total`)."""
    try:
        response = await _respond(request, mount, **kwargs)
    except _Refused as refused:
        response = refused.response
    except ProblemException as exc:
        # M4: a mount answers in url4's envelope, whatever raised on the way (a 409 from the
        # scheduler, an unavailable artifact) — and every answer is counted.
        problem = exc.problem
        response = _envelope(problem.status, _problem_code(problem.status), problem.detail or "")
    counter = getattr(getattr(request.app.state, "metrics", None), "mount_calls", None)
    if counter is not None:
        counter.labels(path=mount.path, status=str(response.status_code)).inc()
    return response


def _shed_message(problem: ProblemException) -> str:
    """The message of a mount call's 503, by cause.

    WHY by cause: `overloaded` is the only 503 code url4 clients know, so it is kept for every
    503, but a broker outage (`RunQueueUnavailable`) is not "at capacity" and must not be
    reported as one.
    """
    if isinstance(problem.__cause__, RunQueueUnavailable):
        return "the run queue is unavailable, retry shortly"
    return "server at capacity, retry shortly"


def _problem_code(status: int) -> str:
    return {404: "result_unavailable", 409: "conflict"}.get(status, "upstream_error")


def _validated(
    request: Request,
    mount: MountDescriptor,
    q: str | None,
    answer_seed: str | None,
    require_identity: bool,
) -> tuple[dict[str, str] | None, int | None, str]:
    """(verified identity, answer seed, direct target) — or `_Refused` before anything queues."""
    # INVARIANT (MC-D3): identity comes ONLY from the verified header, through the same reader
    # `GET /?q=` uses. No other inbound header reaches the run message.
    identity = job_env.identity_from_headers(request.headers)
    if not identity and require_identity:
        raise _Refused(
            _envelope(403, "identity_access_denied", "a verified caller identity is required")
        )
    # INVARIANT (OME-1381): a stated `X-Profile` never reaches a run — refused after the identity
    # check (authentication first) and before every other answer, where the removed node-tier
    # forwarder refused it. Local mode requires no identity, so there it is the first answer.
    if requests_selector(request.headers.getlist(PROFILE_HEADER)):
        raise _Refused(_envelope(400, X_PROFILE_UNSUPPORTED, X_PROFILE_UNSUPPORTED_MESSAGE))
    # INVARIANT (OME-1307): only the run route honours the frozen-copy headers. A mount call would
    # run paid and uncaptured, so either header is refused, whatever its value.
    if states_frozen_copy_mode(request.headers):
        raise _Refused(_envelope(400, CAPTURE_UNSUPPORTED, CAPTURE_UNSUPPORTED_MESSAGE))
    if mount.kind == "endpoint" and q is None:
        raise _Refused(
            _envelope(400, "missing_intent", f"endpoint {mount.path} needs q=(context)!intent")
        )
    try:
        seed = _parse_answer_seed(answer_seed)
    except ProblemException:
        raise _Refused(
            _envelope(400, "malformed_header", "the X-Answer-Seed header must be an integer")
        ) from None
    raw = request.scope.get("query_string", b"")
    # Measured on the RAW bytes: a decoded-then-re-encoded query counts a byte >= 0x80 twice.
    if len(mount.path.encode()) + 1 + len(raw) > job_env.MAX_DIRECT_TARGET_BYTES:
        raise _Refused(_envelope(414, "uri_too_long", "the path and query exceed 8 KiB"))
    query = raw.decode("latin-1")
    target = f"{mount.path}?{query}" if query else mount.path
    return (dict(identity) if identity else None), seed, target


async def _respond(
    request: Request,
    mount: MountDescriptor,
    *,
    require_identity: bool,
    q: str | None,
    prefer: str | None,
    traceparent: str | None,
    answer_seed: str | None,
    cache_control: str | None,
) -> Response:
    deps = _deps(request)
    identity, seed, target = _validated(request, mount, q, answer_seed, require_identity)
    # A mount call has no capability token: the App names its run itself.
    topic = new_topic()
    cap = deps.settings.sync_max_wait_s
    wait_s = _parse_prefer(prefer or "").wait_s
    bound = cap if wait_s is None else min(wait_s, cap)
    clock = getattr(request.app.state, "clock", default_clock)
    # WHY no audience hold (unlike `GET /?q=`, PRD 02): nobody can attach to a mount run, and
    # this handler stops the run itself on every exit that lacks a terminal frame. A hold would
    # only arm the orphan reaper on release — one broker round trip per call, for a run that
    # is already over (review C11).
    try:
        await _schedule(
            deps,
            topic,
            target,
            traceparent=traceparent,
            identity=identity,
            cache=_converge_cache(deps, topic, cache_control, clock),
            answer_seed=seed,
            shape="direct",
            # A direct run never outlives its caller (erd.md §2 invariant).
            deadline_s=int(cap) + 5,
        )
    except ProblemException as exc:
        if exc.problem.status != 503:
            raise
        # url4's `overloaded` shed shape (the removed node tier's), the drain estimate kept.
        raise _Refused(_envelope(503, "overloaded", _shed_message(exc), exc.headers)) from None
    outcome: Any = None
    try:
        outcome = await wait_terminal_or_gone(deps.stream, topic, bound, request.is_disconnected)
    finally:
        if outcome is None or outcome is WAIT_GONE:
            # ans:Q9 and MC-D4: no terminal outcome was read — the bound passed, the caller
            # left, or the wait itself failed or was cancelled. The run is stopped BEFORE any
            # answer: nobody else can ever read it.
            await deps.job_runner.stop(topic)
    if outcome is None or outcome is WAIT_GONE:
        response = _envelope(504, "timeout", "the call did not finish in time; it was stopped")
    else:
        terminated, result = outcome
        response = await _terminal(request, deps, terminated, result)
    # The run behind the answer: an operator (or a test) finds its frames and cost records on
    # subject `url4-cloud.<topic>` of the shared events stream.
    response.headers[RUN_HEADER] = topic
    return response


async def _terminal(
    request: Request, deps: _Deps, terminated: TerminatedEvent, result: ResultEvent | None
) -> Response:
    status = terminated.data.status
    if status == "succeeded":
        return await _success(request, deps, result)
    error = terminated.data.error
    if status == "timed_out":
        return _envelope(504, "timeout", error.message if error else "the call timed out")
    code = error.code if error is not None else None
    permanent = error.permanent if error is not None else True
    message = error.message if error is not None else f"the call ended {status}"
    return _envelope(mount_http_status(code, permanent=permanent), code or status, message)


async def _success(request: Request, deps: _Deps, result: ResultEvent | None) -> Response:
    if result is None:
        # A succeeded run's Result frame always precedes its terminal frame. Missing, it was
        # reclaimed before this handler read it (the run's grace is short, M3): answering an
        # empty 200 would be a silent wrong answer (review C3).
        return _envelope(502, "result_unavailable", "the call's result could not be read")
    artifact = result.data.artifact
    key = deps.settings.artifact_signing_key
    if artifact is not None and artifact.size_bytes > MOUNT_INLINE_LIMIT_BYTES:
        if key:
            location = signed_artifact_path(
                artifact.id, key=key, ttl_s=ARTIFACT_URL_TTL_S, now=time.time
            )
            return Response(status_code=303, headers={"Location": location})
        # MC-D9: with no signing key a 303 would point at an unredeemable URL; stream the body.
        counter = getattr(getattr(request.app.state, "metrics", None), "mount_unsigned_spill", None)
        if counter is not None:
            counter.inc()
        logger.warning("mount result %s over 1 MiB served inline: no signing key", artifact.id)
    return await _result_response(result, deps.artifact_store)


__all__ = [
    "MOUNT_INLINE_LIMIT_BYTES",
    "MOUNT_TAG",
    "RUN_HEADER",
    "install_mounts",
    "register_mounts",
]
