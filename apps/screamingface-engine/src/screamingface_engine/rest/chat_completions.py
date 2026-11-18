"""POST /v1/chat/completions: the OpenAI-compatible chat endpoint (U4, U5).

FEATURE: OpenAI-compatible Engine API (prd/chat-completion.md). The handler runs the stages of
the plan in order: media type, identity and drain (1); body read, parse gate and validation
(2, 3); model resolution, and with tools the checks of the final steps (4, 4b); input write
and schedule with shape `chat` (5); wait (6); answer (7). With `stream: true`, stage 7 answers
as a buffered SSE stream (`rest.chat_stream`, U5); every error before the stream starts keeps
the JSON answer. Each refusal and failure leaves in the OpenAI envelope with fixed, vouched
messages (`rest.chat_errors`); no `application/problem+json` body leaves this route, and an
error that no stage expected leaves as 500 `internal_error` (review F1).

INVARIANT: the input blob is deleted on every exit after its write, and the run is stopped on
every exit that has no terminal frame (`rest.chat_cleanup`). A streamed answer hands both to
its response, which runs them at the end of the stream.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response

from screamingface_engine import job_env
from screamingface_engine.artifacts.blob_schema import BlobScope
from screamingface_engine.artifacts.blobs import BlobStore
from screamingface_engine.auth import ProblemException
from screamingface_engine.auth.token import new_topic
from screamingface_engine.rest.chat_answer import answer
from screamingface_engine.rest.chat_body import (
    ChatBody,
    ParseGate,
    check_media_type,
    read_chat_body,
)
from screamingface_engine.rest.chat_cleanup import ChatCleanup
from screamingface_engine.rest.chat_drain import ChatDrain
from screamingface_engine.rest.chat_errors import ChatError, from_problem
from screamingface_engine.rest.chat_model import ModelLookupCache, recipe_for
from screamingface_engine.rest.chat_observe import RequestFacts, observe
from screamingface_engine.rest.chat_openapi import CHAT_RESPONSES, CHAT_TAG, REQUEST_BODY
from screamingface_engine.rest.chat_stream import ChatStreamResponse, StreamPlan, stream_answer
from screamingface_engine.rest.chat_tools import check_tool_steps
from screamingface_engine.rest.chat_wait import settle_wait, wait_for_run
from screamingface_engine.rest.routes import (
    _converge_cache,
    _Deps,
    _deps,
    _schedule,
    default_clock,
)
from screamingface_engine.rest.runs_boundary import request_caller
from url4.streaming.trace import parse_traceparent, valid_traceparent

__all__ = ["CHAT_PATH", "install_chat_state", "router"]

CHAT_PATH = "/v1/chat/completions"

router = APIRouter()

_logger = logging.getLogger(__name__)

_EMAIL_HEADER = "X-User-Email"


def install_chat_state(app: FastAPI) -> None:
    """The per-App state of the chat route: the drain, the parse gate and the lookup cache."""
    app.state.chat_drain = ChatDrain()
    app.state.chat_parse_gate = ParseGate()
    app.state.chat_model_cache = ModelLookupCache()


@router.post(
    CHAT_PATH,
    tags=[CHAT_TAG],
    summary="Create a chat completion (OpenAI-compatible)",
    description=(
        "Run a Candidate URL4, or a gateway model id as a one-model recipe, on the client "
        "messages and answer as an OpenAI chat completion. Errors use the OpenAI "
        '`{"error": {"message", "type", "param", "code"}}` envelope with `x-should-retry`.'
    ),
    responses=CHAT_RESPONSES,
    openapi_extra=REQUEST_BODY,
    response_model=None,
)
async def chat_completions(request: Request) -> Response:
    """One chat completion, counted by outcome, timed and logged once."""
    started = time.monotonic()
    facts = RequestFacts()

    def finish(outcome: str, status: int) -> None:
        observe(request, facts, outcome, status, time.monotonic() - started)

    try:
        response: Response = await _complete(request, facts)
        outcome = "ok"
    except ChatError as exc:
        response, outcome = exc.response(), exc.code
    # WHY: this is the one boundary of the route. An error that no stage expected still answers
    # in the OpenAI envelope with x-should-retry false: an OpenAI SDK retries a bare 500, and
    # each retry runs the full ensemble again. The cleanup already ran in `_complete`. Only the
    # class name is logged, as the message can quote a request or a provider. A cancel is a
    # BaseException and passes.
    except Exception as exc:
        _logger.error(
            "chat request failed trace_id=%s: %s", facts.trace_id or "-", type(exc).__name__
        )
        response, outcome = ChatError(500, "internal_error").response(), "internal_error"
    if isinstance(response, ChatStreamResponse):
        # WHY: a streamed answer is observed once, at the end of its stream.
        response.on_end = finish
        return response
    finish(outcome, response.status_code)
    return response


@dataclass(frozen=True)
class _Turn:
    """One request after stage 4: what its run needs. It holds no request content (CC-S35)."""

    deps: _Deps
    identity: dict[str, str] | None
    model: str
    recipe: str
    traceparent: str | None
    topic: str
    stream: bool
    include_usage: bool


async def _complete(request: Request, facts: RequestFacts) -> Response:
    state = request.app.state
    check_media_type(request.headers.get("content-type"))
    identity = _identity(request)
    drain: ChatDrain = state.chat_drain
    _refuse_drained(drain)
    store = _chat_input_store(state)
    deps = _deps_or_error(request)
    traceparent = valid_traceparent(request.headers.get("traceparent"))
    facts.trace_id = parse_traceparent(traceparent)
    body = await read_chat_body(request, state.chat_parse_gate)
    facts.digest, facts.size, facts.messages = body.digest, body.size, body.messages
    recipe = await _recipe(state, body, identity, traceparent)
    topic = new_topic()
    scope = BlobScope.for_caller((identity or {}).get(_EMAIL_HEADER), topic)
    cleanup = ChatCleanup(store, scope, body.digest, deps.job_runner.stop, topic)
    turn = _Turn(
        deps, identity, body.model, recipe, traceparent, topic, body.stream, body.include_usage
    )
    handed_over = False
    try:
        ref = await cleanup.write(body)
        response = await _run(request, turn, cleanup, ref, facts)
        # INVARIANT: once the stream response exists, its __call__ owns the cleanup.
        handed_over = isinstance(response, ChatStreamResponse)
        return response
    finally:
        if not handed_over:
            await cleanup.run()


async def _recipe(
    state: Any, body: ChatBody, identity: dict[str, str] | None, traceparent: str | None
) -> str:
    """Stage 4: the recipe of the run; with tools, stage 4b: the with-tools recipe check
    (TC-S7 to TC-S11), then the tool support of each final model (TC-S10).

    INVARIANT: each refusal comes before the input write, so no blob and no run exist.
    """
    recipe = await recipe_for(
        body.model,
        identity=identity,
        source=state.model_parameters,
        cache=state.chat_model_cache,
        traceparent=traceparent,
    )
    if body.has_tools:
        await check_tool_steps(recipe, identity=identity, catalog=state.catalog)
    return recipe


def _identity(request: Request) -> dict[str, str] | None:
    """CC-S10: the verified identity; 401 when a hosted request has none (the /runs rule)."""
    if request_caller(request) is None:
        raise ChatError(401, "identity_required")
    return job_env.identity_from_headers(request.headers) or None


def _refuse_drained(drain: ChatDrain) -> None:
    """CC-S37: after the stop signal, a new request schedules nothing."""
    if drain.requested:
        raise ChatError(503, "server_restarting", should_retry=True)


def _chat_input_store(state: Any) -> BlobStore:
    """CC-S20: no blob store is a permanent 503, before any work."""
    store: BlobStore | None = state.chat_input_store
    if store is None:
        raise ChatError(503, "chat_unavailable")
    return store


def _deps_or_error(request: Request) -> _Deps:
    try:
        return _deps(request)
    except ProblemException as exc:
        raise from_problem(exc) from exc


async def _run(
    request: Request,
    turn: _Turn,
    cleanup: ChatCleanup,
    ref: str,
    facts: RequestFacts,
) -> Response:
    """Stages 5 to 7, after the input write."""
    drain: ChatDrain = request.app.state.chat_drain
    _refuse_drained(drain)
    cleanup.scheduling = True
    try:
        await _schedule_chat(request, turn, ref)
    except ChatError as exc:
        # WHY: a refused schedule queued nothing, so there is no run to stop (CC-S28). A start
        # that is not confirmed (`queue_unavailable`, rest/routes.py) can still sit in the
        # broker, so its run is stopped (review F6).
        cleanup.scheduling = exc.code == "queue_unavailable"
        raise
    settings = turn.deps.settings
    if turn.stream:
        plan = StreamPlan(
            events=turn.deps.stream,
            topic=turn.topic,
            model=turn.model,
            include_usage=turn.include_usage,
            max_wait_s=settings.chat_max_wait_s,
            keepalive_s=settings.chat_keepalive_s,
            drain=drain,
            artifacts=turn.deps.artifact_store,
        )
        return stream_answer(plan, cleanup, facts)
    frames = settle_wait(
        await wait_for_run(
            turn.deps.stream, turn.topic, settings.chat_max_wait_s, request.receive, drain
        ),
        cleanup,
        facts,
    )
    return await answer(frames, turn.model, turn.deps.artifact_store)


async def _schedule_chat(request: Request, turn: _Turn, ref: str) -> None:
    """C5: schedule the `chat` run; capture is off and the frozen-copy headers have no effect."""
    deps = turn.deps
    # WHY getattr: create_app sets `clock` only when a test gives one.
    clock = getattr(request.app.state, "clock", default_clock)
    try:
        await _schedule(
            deps,
            turn.topic,
            turn.recipe,
            traceparent=turn.traceparent,
            identity=turn.identity,
            cache=_converge_cache(deps, turn.topic, request.headers.get("cache-control"), clock),
            shape="chat",
            chat_input=ref,
            # INVARIANT: the rule of a mount call: the run never outlives its caller.
            deadline_s=int(deps.settings.chat_max_wait_s) + 5,
            capture=False,
            owner=request_caller(request) or "anonymous",
        )
    except ProblemException as exc:
        raise from_problem(exc) from exc
