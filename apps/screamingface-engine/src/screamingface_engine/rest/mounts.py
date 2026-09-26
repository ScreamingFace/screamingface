"""Mount calls as direct runs (uniform executor PRD 04, contracts.md C2).

Every mount the declared world serves — an endpoint (`GET /<path>?q=(context)!intent`) or a data
route (`GET /<path>`) — is a FastAPI `GET` operation of its own, tagged `Mounts`, so it appears in
`/openapi.json` (ans:Q5). All of them run the SAME workflow as any other run: the App queues a
`shape=direct` run, holds its topic while it waits (the PRD 02 hold), and answers from the run's
terminal frame. A worker's child runs the ONE handler through `url4.peer.dispatch_direct` (D1).

The answers match the node tier's (MNT-C2, MNT-9): url4's error envelope
(`{"error": {"code", "message"}}`) and the status url4 would have given the code.

- identity: the verified `X-User-Email`, from the same source as `GET /?q=` — none → 403
- endpoint without `q` → 400 `missing_intent`; a bad `X-Answer-Seed` → 400 `malformed_header`
- target over 8 KiB → 414; admission refused → 503 `overloaded` + `Retry-After`
- bound (`min(Prefer wait, 30 s)`) passes → the run is STOPPED, then 504 (ans:Q9)
- the caller disconnects → the run is stopped (nobody can attach to a mount run)
- result ≤ 1 MiB → 200 inline; over it → 303 to a signed `/artifacts/{id}` (ans:Q10)
"""

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import Response

from screamingface_engine import job_env
from screamingface_engine.artifacts.signing import signed_artifact_path
from screamingface_engine.auth.problem import ProblemException
from screamingface_engine.rest.routes import (
    _await_terminal,
    _converge_cache,
    _Deps,
    _deps,
    _parse_answer_seed,
    _parse_prefer,
    _result_response,
    _schedule,
    _until_disconnected,
    default_clock,
)
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
"""How long a mount's signed artifact URL is valid (the node tier's value)."""

_MOUNT_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "The handler's body, with the route's media type."},
    303: {"description": "The result is over 1 MiB: `Location` is a signed artifact URL."},
    400: {"description": "`missing_intent`, a malformed `q`, or a bad `X-Answer-Seed`."},
    403: {"description": "No verified caller identity."},
    404: {"description": "The world has no such handler."},
    414: {"description": "The path plus query is longer than 8 KiB."},
    502: {"description": "The handler or its upstream failed."},
    503: {"description": "At capacity (`Retry-After`)."},
    504: {"description": "The bound passed; the run was stopped."},
}


def _envelope(status: int, code: str, message: str, headers: dict[str, str] | None = None):
    """url4's error envelope — the node tier's error shape, byte for byte."""
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


def register_mounts(app: FastAPI, table: MountTable) -> None:
    """Register `table`'s mounts as `GET` routes and forget any cached OpenAPI schema (MC-D8)."""
    for mount in table.mounts:
        app.router.add_api_route(
            mount.path,
            _handler_for(mount),
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
    app.state.mount_table = table
    # `/healthz` reports which config file the mounts came from (erd.md §2, R11).
    app.state.config_digest = table.config_digest
    # INVARIANT (MC-D8): a schema generated before the mounts existed must never be served again.
    app.openapi_schema = None


def _handler_for(mount: MountDescriptor) -> Callable[..., Awaitable[Response]]:
    async def call_mount(
        request: Request,
        q: Annotated[
            str | None,
            Query(description="`(context)!intent` for an endpoint; optional for a data route."),
        ] = None,
        prefer: Annotated[str | None, Header(alias="Prefer")] = None,
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
        x_profile: Annotated[str | None, Header(alias="X-Profile")] = None,
        x_answer_seed: Annotated[str | None, Header(alias="X-Answer-Seed")] = None,
        cache_control: Annotated[str | None, Header(alias="Cache-Control")] = None,
    ) -> Response:
        return await _call(
            request,
            mount,
            q=q,
            prefer=prefer,
            traceparent=traceparent,
            profile=x_profile,
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
    counter = getattr(getattr(request.app.state, "metrics", None), "mount_calls", None)
    if counter is not None:
        counter.labels(path=mount.path, status=str(response.status_code)).inc()
    return response


def _validated(
    request: Request, mount: MountDescriptor, q: str | None, answer_seed: str | None
) -> tuple[dict[str, str], int | None, str]:
    """(verified identity, answer seed, direct target) — or `_Refused` before anything queues."""
    # INVARIANT (MC-D3): identity comes ONLY from the verified header, through the same reader
    # `GET /?q=` uses. No other inbound header reaches the run message.
    identity = job_env.identity_from_headers(request.headers)
    if not identity:
        raise _Refused(
            _envelope(403, "identity_access_denied", "a verified caller identity is required")
        )
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
    raw_query = request.scope.get("query_string", b"").decode("latin-1")
    target = f"{mount.path}?{raw_query}" if raw_query else mount.path
    if len(target.encode()) > job_env.MAX_DIRECT_TARGET_BYTES:
        raise _Refused(_envelope(414, "uri_too_long", "the path and query exceed 8 KiB"))
    return dict(identity), seed, target


async def _respond(
    request: Request,
    mount: MountDescriptor,
    *,
    q: str | None,
    prefer: str | None,
    traceparent: str | None,
    profile: str | None,
    answer_seed: str | None,
    cache_control: str | None,
) -> Response:
    deps = _deps(request)
    identity, seed, target = _validated(request, mount, q, answer_seed)
    # A mount call has no capability token: the App names its run itself.
    topic = secrets.token_hex(32)
    cap = deps.settings.sync_max_wait_s
    wait_s = _parse_prefer(prefer or "").wait_s
    bound = cap if wait_s is None else min(wait_s, cap)
    clock = getattr(request.app.state, "clock", default_clock)
    async with deps.sessions.hold_sync(topic):
        try:
            await _schedule(
                deps,
                topic,
                target,
                traceparent=traceparent,
                profile=profile,
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
            # The node tier's shed shape: url4's `overloaded` envelope, the drain estimate kept.
            raise _Refused(
                _envelope(503, "overloaded", "server at capacity, retry shortly", exc.headers)
            ) from None
        outcome = await _wait(deps, topic, bound, request)
    return await _answer(request, deps, topic, outcome)


_GONE = object()


async def _wait(deps: _Deps, topic: str, bound_s: float, request: Request) -> Any:
    """The run's terminal outcome; None when the bound passed; `_GONE` when the caller left."""
    wait = asyncio.ensure_future(_await_terminal(deps.stream, topic, bound_s))
    gone = asyncio.ensure_future(_until_disconnected(request.is_disconnected))
    try:
        await asyncio.wait({wait, gone}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (wait, gone):
            task.cancel()
        await asyncio.gather(wait, gone, return_exceptions=True)
    if wait.cancelled():
        return _GONE
    return wait.result()


async def _answer(request: Request, deps: _Deps, topic: str, outcome: Any) -> Response:
    if outcome is None or outcome is _GONE:
        # ans:Q9 — and MC-D4: nobody can attach to a mount run, so a run whose caller is gone
        # or out of time is stopped at once, BEFORE the answer (no reaper grace applies).
        await deps.job_runner.stop(topic)
        return _envelope(504, "timeout", "the call did not finish in time; it was stopped")
    terminated, result = outcome
    return _terminal(request, deps, terminated, result)


def _terminal(
    request: Request, deps: _Deps, terminated: TerminatedEvent, result: ResultEvent | None
) -> Response:
    status = terminated.data.status
    if status == "succeeded":
        return _success(request, deps, result)
    error = terminated.data.error
    if status == "timed_out":
        return _envelope(504, "timeout", error.message if error else "the call timed out")
    code = error.code if error is not None else None
    permanent = error.permanent if error is not None else True
    message = error.message if error is not None else f"the call ended {status}"
    return _envelope(mount_http_status(code, permanent=permanent), code or status, message)


def _success(request: Request, deps: _Deps, result: ResultEvent | None) -> Response:
    artifact = result.data.artifact if result is not None else None
    if artifact is None or artifact.size_bytes <= MOUNT_INLINE_LIMIT_BYTES:
        return _result_response(result, deps.artifact_store)
    key = deps.settings.artifact_signing_key
    if key:
        location = signed_artifact_path(
            artifact.id, key=key, ttl_s=ARTIFACT_URL_TTL_S, now=time.time
        )
        return Response(status_code=303, headers={"Location": location})
    # MC-D9: with no signing key a 303 would point at an unredeemable URL; stream the body.
    counter = getattr(getattr(request.app.state, "metrics", None), "mount_unsigned_spill", None)
    if counter is not None:
        counter.inc()
    logger.warning("mount result %s over 1 MiB served inline: no artifact signing key", artifact.id)
    return _result_response(result, deps.artifact_store)


__all__ = ["MOUNT_INLINE_LIMIT_BYTES", "MOUNT_TAG", "install_mounts", "register_mounts"]
