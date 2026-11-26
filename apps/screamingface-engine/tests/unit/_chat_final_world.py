"""The gateway world of a chat turn with tools, for tests: a stub gateway and the final route.

Test-only, the `_chat_world` pattern. `ToolGateway` answers each model call from a table of
`Reply` values (a reply can carry tool calls, a status, a cache state and a refusal) and keeps
each request body and its headers. `tools_world` builds the gateway world with every route a
chat run needs, the final-step routes included. `final_turn` builds a bound turn from a client
request the way the chat route does, `chat_run` binds the chat-run marker, and `call_final`
evaluates one source on a final route.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from _signal_world import _body

from screamingface_engine.chat.input import chat_input_from_request
from screamingface_engine.chat.recipe import FINAL_STEP_ROUTE
from screamingface_engine.chat.views import text_view
from screamingface_engine.chat.wire import ChatCompletionRequest
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.attachment_parts import BlobReader
from screamingface_engine.world.branch import install_branch_runtime
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.chat_final import FinalTurn, final_turn_scope, install_chat_final
from screamingface_engine.world.chat_turn import chat_run_scope, install_chat_turn
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.models.registry import decode_route_id, encode_route_id
from url4 import RelExpr, expr, render, src, text
from url4.peer.server import Url4Node

__all__ = [
    "INPUT_MESSAGES",
    "TOOL",
    "Reply",
    "ToolGateway",
    "call_final",
    "chat_run",
    "final_recipe",
    "final_route",
    "final_turn",
    "reply_body",
    "tool_call",
    "tools_world",
]

TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Weather for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}
INPUT_MESSAGES: list[dict[str, Any]] = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "Weather in Paris?"},
]


def tool_call(
    call_id: str = "call_1",
    name: str = "get_weather",
    arguments: str = '{"city":"Paris"}',
    **extra: Any,
) -> dict[str, Any]:
    """One tool call as a provider returns it."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
        **extra,
    }


@dataclass(frozen=True)
class Reply:
    """One gateway answer: a 200 body, or an error status with a fixed error code."""

    content: str | None = "ok"
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str | None = "stop"
    status: int = 200
    error_code: str = "model_parameter_invalid"
    cache: str = "miss"
    refusal: str | None = None


def reply_body(reply: Reply) -> dict[str, Any]:
    """The 200 body of `reply`: 10 + 4 tokens, as `_signal_world` builds it."""
    body = _body(reply.content or "", "0.001", reply.cache)
    choice = body["choices"][0]
    message = choice["message"]
    message["content"] = reply.content
    if reply.tool_calls is not None:
        message["tool_calls"] = reply.tool_calls
    if reply.refusal is not None:
        message["refusal"] = reply.refusal
    if reply.finish_reason is None:
        choice.pop("finish_reason", None)
    else:
        choice["finish_reason"] = reply.finish_reason
    return body


type ReplyRule = Reply | list[Reply] | Callable[[dict[str, Any]], Reply]


@dataclass
class ToolGateway:
    """A fake gateway: one reply rule per model; each request body and its headers are kept.

    A list of replies is played in order, one per call, and its last reply repeats.
    """

    replies: Mapping[str, ReplyRule]
    seen: list[dict[str, Any]] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)

    def calls(self, model: str) -> int:
        return sum(1 for sent in self.seen if sent["model"] == model)

    def _reply(self, sent: dict[str, Any]) -> Reply:
        rule = self.replies[sent["model"]]
        if isinstance(rule, Reply):
            return rule
        if isinstance(rule, list):
            return rule[min(self.calls(sent["model"]), len(rule)) - 1]
        return rule(sent)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        self.seen.append(sent)
        self.headers.append(dict(request.headers))
        reply = self._reply(sent)
        if reply.status != 200:
            retry = {"Retry-After": "0"} if reply.status == 429 else {}
            return httpx.Response(
                reply.status,
                headers=retry,
                json={"error": {"code": reply.error_code, "message": "fixed refusal"}},
            )
        return httpx.Response(200, headers={"X-AIGW-Cache": reply.cache}, json=reply_body(reply))


@asynccontextmanager
async def tools_world(
    gateway: ToolGateway, *, models: Sequence[ModelSpec] | None = None
) -> AsyncIterator[Url4Node]:
    """The gateway world of a chat run with tools, with every route it needs, over `gateway`."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    specs = (
        tuple(models)
        if models is not None
        else tuple(ModelSpec(id=model, web_search=False) for model in gateway.replies)
    )
    cfg = AigatewayConfig(default_model=specs[0].id, models=specs)
    world = await build_aigateway_world(cfg, client=client)
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        install_branch_runtime(world.node)
        install_chat_turn(world.node)
        install_chat_final(world, cfg)
        yield world.node
    finally:
        await world.aclose()
        await client.aclose()


def _no_reader() -> BlobReader:
    raise AssertionError("a final step never reads the chat input")


@contextmanager
def chat_run() -> Iterator[None]:
    """Bind the chat-run marker with a reader that a final step must never use."""
    with chat_run_scope(_no_reader):
        yield


def final_route(model: str) -> str:
    """The final-step route of `model`, given as the gateway id or as its route id.

    The route id writes `~` for `:`, as `install_chat_final` registers it; the decode first
    makes a route-form id give the same path as its gateway id.
    """
    return FINAL_STEP_ROUTE + "/" + encode_route_id(decode_route_id(model))


def final_turn(
    messages: list[dict[str, Any]] = INPUT_MESSAGES,
    tools: list[dict[str, Any]] | None = None,
    *,
    request_extra: dict[str, Any] | None = None,
) -> FinalTurn:
    """The turn of one client request, read through the wire model as the chat route reads it.

    Top-level client fields (tool_choice, temperature, max_tokens, ...) drop at validation.
    """
    request = ChatCompletionRequest.model_validate(
        {"model": "m", "messages": messages, "tools": tools or [TOOL], **(request_extra or {})}
    )
    record = chat_input_from_request(request)
    return FinalTurn(
        messages=tuple(record.messages),
        tools=tuple(record.tools or ()),
        input_text=text_view(record.messages, record.tools),
    )


def final_recipe(
    model: str,
    *,
    intent: str = "",
    context: str | None = None,
    params: tuple[tuple[str, str], ...] = (("binding", "model_1"),),
    binding: str = "model_1",
) -> str:
    """A recipe of one source on the final route of `model`; its context is `$input` by default."""
    return render(
        expr(
            src(
                RelExpr(
                    path=final_route(model),
                    context="$input" if context is None else render(text(context)),
                    intent=text(intent),
                    params=params,
                ),
                name=binding,
                weight=0.0,
            ),
            intent=text("$" + binding),
        )
    )


async def call_final(
    node: Url4Node,
    model: str,
    *,
    turn: FinalTurn | None,
    intent: str = "",
    context: str | None = None,
    params: tuple[tuple[str, str], ...] = (("binding", "model_1"),),
    binding: str = "model_1",
    scope: RequestScope | None = None,
    in_chat_run: bool = True,
) -> str:
    """Evaluate one source on the final route of `model` with `turn` bound; its text.

    With `in_chat_run` the chat-run marker is bound too, as the chat run binds it.
    """
    recipe = final_recipe(model, intent=intent, context=context, params=params, binding=binding)
    with ExitStack() as stack:
        stack.enter_context(request_scope(scope or RequestScope(origin="run")))
        if in_chat_run:
            stack.enter_context(chat_run())
        stack.enter_context(final_turn_scope(turn))
        result = await node.evaluate(recipe, env={"input": turn.input_text if turn else "{}"})
    return result.text
