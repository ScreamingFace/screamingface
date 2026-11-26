"""The final-step endpoint of a chat turn with tools (tool-calls PRD §3.2, contracts C8).

FEATURE: tool-calls §3.2. When the client request has tools, the chat handler re-points each
final model step of its copy of the recipe to `/ensemble/chat/v1/final/<route id>`. This
endpoint sends that step to the gateway with the native messages of the conversation (§3.5) and
the client tools, through the shared round trip, and hands the tool calls, the provider
`finish_reason` and the accounting of the call to the handler through a run-scoped collector.
INVARIANT: exactly one gateway request per call. There is no tool loop, and no tool is run.
INVARIANT: no log holds message or tool content. A log names the binding and a count only.
INVARIANT: the endpoint fails closed, before any other work, when the chat-run marker or the chat
turn is not bound.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx
from pydantic import ValidationError

from screamingface_engine.chat import wire
from screamingface_engine.chat.recipe import FINAL_SEARCH_MESSAGE, FINAL_STEP_ROUTE
from screamingface_engine.chat.views import native_messages
from screamingface_engine.model_outcomes import bind_model_outcome, record_model_outcome
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    ReplyLogprobs,
    SignalAccounting,
    combine_operation_accounting,
    combine_signal_accounting,
)
from screamingface_engine.operation_calls import operation_call_identity, record_operation_call
from screamingface_engine.request_scope import current_scope
from screamingface_engine.world import connector, gateway_transport
from screamingface_engine.world.chat_marker import chat_run_reader
from screamingface_engine.world.config import ModelSpec, provider_of, routes_for
from screamingface_engine.world.connector import AigatewayConfig, AigatewayWorld
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.models.registry import decode_route_id
from screamingface_engine.world.request_parameters import (
    OPERATION_BINDING_PARAM,
    WEB_SEARCH_PARAM,
    caller_exclusions,
    model_params,
    wants_web_search,
)
from url4.core.errors import ErrorCode, ResolutionError
from url4.peer.server import Request

__all__ = [
    "FINAL_STEP_AMBIGUOUS",
    "ChatFinalEndpoint",
    "FinalCall",
    "FinalCalls",
    "FinalTurn",
    "current_final_turn",
    "final_turn_scope",
    "install_chat_final",
]

FINAL_STEP_AMBIGUOUS = "final_step_ambiguous"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FinalCall:
    """The facts of one final step: what the handler needs for the CHAT_RESULT (erd §2.4).

    `finish_reason` is the provider value, unchanged. The real gateway model id is
    `accounting.request_model`.
    """

    binding: str
    tool_calls: tuple[wire.ToolCall, ...]
    finish_reason: str | None
    accounting: OperationAccounting | None


class FinalCalls:
    """The run-scoped collector that the final-step endpoint fills."""

    __slots__ = ("_calls",)

    def __init__(self) -> None:
        self._calls: list[FinalCall] = []

    def add(self, call: FinalCall) -> None:
        self._calls.append(call)

    def __len__(self) -> int:
        return len(self._calls)

    def result(self) -> FinalCall | None:
        """The one final call, or None when no final step ran.

        Raises:
            ResolutionError: `final_step_ambiguous`, permanent, when two or more final steps
                ran (TC-S16). The message names no value.
        """
        if len(self._calls) > 1:
            # INVARIANT: the Engine never picks one of two final results.
            raise ResolutionError(
                "more than one final step ran", code=FINAL_STEP_AMBIGUOUS, permanent=True
            )
        return self._calls[0] if self._calls else None


@dataclass(frozen=True, slots=True)
class FinalTurn:
    """The conversation and the tools of one chat turn, bound for its final steps.

    `input_text` is the text view that the turn binds to `$input`.
    """

    messages: tuple[wire.ClientMessage, ...]
    tools: tuple[wire.ToolSpec, ...]
    input_text: str
    calls: FinalCalls = field(default_factory=FinalCalls)


# WHY a ContextVar: the turn exists only inside one chat turn with tools, and each final step of
# that turn's evaluation runs in a task that inherits it, as the chat-run marker does.
_final_turn: contextvars.ContextVar[FinalTurn | None] = contextvars.ContextVar(
    "screamingface_engine_chat_final_turn", default=None
)


@contextmanager
def final_turn_scope(turn: FinalTurn | None) -> Iterator[None]:
    """Bind `turn` to the enclosed calls."""
    token = _final_turn.set(turn)
    try:
        yield
    finally:
        _final_turn.reset(token)


def current_final_turn() -> FinalTurn | None:
    """The bound chat turn, or None outside a chat turn with tools."""
    return _final_turn.get()


def _tool_calls(raw: object) -> tuple[wire.ToolCall, ...]:
    """The tool calls of the reply, validated as data (C8: the response is untrusted input)."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _bad_response()
    try:
        return tuple(wire.ToolCall.model_validate(item) for item in raw)
    except ValidationError:
        # WHY from None: a validation error quotes the reply, and its content must not reach a log.
        raise _bad_response() from None


def _bad_response() -> RunnerRequestError:
    return RunnerRequestError(
        "malformed aigateway response", code="aigateway_bad_response", permanent=True
    )


def _search_fields(params: Mapping[str, str], spec: ModelSpec) -> dict[str, object]:
    """The search flag fields of the final step (tool-calls §3.2).

    The endpoint has no tool loop, so a route that uses the Engine web tools does not search,
    also when its default is on. A route where the provider searches keeps the route rule.

    Raises:
        ResolutionError: `recipe_not_supported` when the step asks for a search on a route that
            uses the Engine web tools (TC-S11).
        RunnerRequestError: a bad `web_search` or `web_search_exclude` value.
    """
    if params.get(WEB_SEARCH_PARAM) == "true" and spec.uses_web_tools:
        raise ResolutionError(FINAL_SEARCH_MESSAGE, code="recipe_not_supported", permanent=True)
    if not (wants_web_search(params, spec) and spec.uses_native_web_search):
        return {}
    fields: dict[str, object] = {"web_search": True}
    exclusions = caller_exclusions(params)
    if exclusions:
        fields["web_search_excluded_domains"] = list(exclusions)
    return fields


class ChatFinalEndpoint:
    """The handler registered on each final-step route.

    It holds world-level state only (the gateway client, the config and the routes). The turn
    and the caller come from the context of each call.
    """

    __slots__ = ("_cfg", "_http_client", "_routes")

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        cfg: AigatewayConfig,
        routes: Mapping[str, ModelSpec],
    ) -> None:
        self._http_client = http_client
        self._cfg = cfg
        self._routes = routes

    async def __call__(self, request: Request) -> str:
        turn = current_final_turn()
        if chat_run_reader() is None or turn is None:
            raise ResolutionError(
                "the final-step route runs only in a chat turn with tools",
                code=ErrorCode.ENDPOINT_NOT_FOUND,
                permanent=True,
            )
        spec = self._routes[request.path]
        binding = request.params.get(OPERATION_BINDING_PARAM)
        if not binding:
            raise ResolutionError(
                "a final step has no binding", code="internal_error", permanent=True
            )
        try:
            with operation_call_identity(
                request.path, request.params, context=request.context, intent=request.intent
            ):
                return await self._send(turn, spec, binding, request)
        except gateway_transport._GatewayRefusal as exc:
            # INVARIANT (OME-1770 review): the same answer as the model endpoint for a private
            # route that the account may not use.
            if spec.public_schema or not exc.refuses_provider(provider_of(spec.id)):
                raise
            raise connector._undeclared_route(request.path.removeprefix(FINAL_STEP_ROUTE)) from None
        except RunnerRequestError as exc:
            # WHY the error form of the model endpoint: a provider refusal then gives a refused
            # Candidate result (TC-S25).
            error = ResolutionError(str(exc), code=exc.code, permanent=exc.permanent)
            if exc.outcome is not None:
                bind_model_outcome(error, exc.outcome)
            raise error from exc

    async def _send(self, turn: FinalTurn, spec: ModelSpec, binding: str, request: Request) -> str:
        real = decode_route_id(spec.id)
        scope = current_scope()
        headers = {
            **gateway_transport._headers(scope),
            **gateway_transport.timeout_headers(self._cfg.timeout_s, self._cfg.admission_timeout_s),
        }
        search = _search_fields(request.params, spec)
        sampling = model_params(request.params)
        # INVARIANT (ans:Q14): no tool_choice, no parallel_tool_calls, no stream and no client
        # sampling field. The gateway refuses an unknown top-level key.
        body: dict[str, object] = {
            "model": real,
            "messages": native_messages(
                turn.messages,
                instruction=request.intent or "",
                context=request.context,
                input_text=turn.input_text,
            ),
            "tools": [wire.tool_dict(tool) for tool in turn.tools],
            **sampling,
            **search,
        }
        operation_accounting: list[OperationAccounting | None] = []
        signal_accounting: list[SignalAccounting] = []
        reply_rounds: list[ReplyLogprobs | None] = []
        choice = await gateway_transport.round_trip(
            self._http_client,
            real_model_id=real,
            headers=headers,
            body=body,
            cache=scope.cache,
            max_tokens=sampling.get("max_tokens"),
            operation_accounting=operation_accounting,
            replay_frozen_copy=scope.replay_frozen_copy,
            signal_accounting=signal_accounting,
            reply_logprobs=reply_rounds,
        )
        tool_calls = _tool_calls(choice.tool_calls)
        content = choice.content or ""
        record_model_outcome(choice.finish_reason, choice.refusal)
        accounting = combine_operation_accounting(operation_accounting)
        record_operation_call(
            content,
            choice.finish_reason,
            accounting,
            combine_signal_accounting(signal_accounting),
            reply_logprobs=reply_rounds[-1] if reply_rounds else None,
        )
        turn.calls.add(FinalCall(binding, tool_calls, choice.finish_reason, accounting))
        _logger.info("chat final step binding=%s tool_calls=%d", binding, len(tool_calls))
        return content


def install_chat_final(world: AigatewayWorld, cfg: AigatewayConfig) -> None:
    """Register the final-step route of each declared model on the gateway world (prd §3.2).

    Call it after the direct-mount snapshot, so the routes are never public mounts. A [data]
    mount at a final path makes `node.endpoint` raise ValueError, which propagates.
    """
    routes = {FINAL_STEP_ROUTE + path: spec for path, spec in routes_for(cfg.models).items()}
    endpoint = ChatFinalEndpoint(http_client=world._client, cfg=cfg, routes=routes)
    registered = set(world.node.processor_routes())
    for path in routes:
        if path not in registered:
            world.node.endpoint(path)(endpoint)
