"""The shared chat call of each surface: the checks, the send and the endpoint values.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.1, C1.2 and
C1.5; overview §5.5, D13 to D16). ``client.chat``, ``aclient.chat``, ``recipe.chat`` and
``sf.chat`` call the two functions of this module, so the four surfaces have one implementation.
AIDEV-NOTE: each create method calls create_sync or create_async directly, with no frame between
them, so the IgnoredParameterWarning names the line of the caller (see _CALLER_STACKLEVEL).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from screamingface import _default_client
from screamingface._inference import transport
from screamingface._inference.error_map import client_timeout
from screamingface._inference.request import (
    ChatCall,
    ModelSource,
    chat_call,
    chat_messages,
    chat_tools,
    check_options,
    check_other,
    model_source,
    model_text,
    model_text_async,
    refuse_tool_use,
    timeout_seconds,
)
from screamingface._inference.trace import new_trace_context
from screamingface._inference.transport import (
    open_chat_stream,
    open_chat_stream_async,
    send_chat,
    send_chat_async,
)
from screamingface.chat_completion import AsyncChatStream, ChatCompletion, ChatStream

if TYPE_CHECKING:
    import httpx

    from screamingface.client import AsyncClient, Client
    from screamingface.inference import InferenceEndpoint

# WHY 5: the frames are check_other (1), _checked (2), create_sync or create_async (3), the
# create method of a surface (4) and the line of the caller (5).
_CALLER_STACKLEVEL = 5


def _checked(
    model: object,
    prompt: object,
    *,
    messages: object,
    tools: object,
    stream: bool,
    stream_options: Mapping[str, Any] | None,
    use_cache: bool,
    max_retries: int | None,
    timeout: float | httpx.Timeout | None,
    other: Mapping[str, Any],
) -> tuple[ModelSource, Callable[[str, int, float | None], ChatCall]]:
    """Check the arguments of one chat call; give its model source and its call builder (C1.2).

    It sends no request and takes no client, so an argument error makes no default client.
    """

    source = model_source(model)
    messages_list = chat_messages(prompt, messages)
    tools_list = chat_tools(tools)
    check_options(
        stream=stream,
        stream_options=stream_options,
        use_cache=use_cache,
        max_retries=max_retries,
        timeout=timeout,
    )
    # WHY before check_other: a call that raises gives no warning (C1.2).
    refuse_tool_use(messages_list, tools_list)
    check_other(other, stacklevel=_CALLER_STACKLEVEL)

    def build(text: str, max_retries: int, timeout: float | None) -> ChatCall:
        # WHY at the send: the limits can come from the client (D21).
        return chat_call(
            text,
            messages=messages_list,
            tools=tools_list,
            stream=stream,
            stream_options=stream_options,
            use_cache=use_cache,
            max_retries=max_retries,
            timeout=timeout,
        )

    return source, build


def _limits(
    client: Client | AsyncClient, max_retries: int | None, timeout: object
) -> tuple[int, float | None]:
    """The retry count and the time limit of one call: the value of the call, or else the default
    of its client (C1.7, D21)."""

    return (
        client._chat_max_retries if max_retries is None else max_retries,
        client._chat_timeout if timeout is None else timeout_seconds(timeout),
    )


def _time_left(limit: float | None, started: float) -> float | None:
    """The part of the call limit that is left after the model resolution (contracts C1 P11).

    The limit is the limit of the full call, so the catalogue read and the compile count.
    """

    if limit is None:
        return None
    left = limit - (transport._clock() - started)
    if left <= 0:
        # WHY: the limit passed before the request, so no request is sent.
        raise client_timeout(new_trace_context().trace_id)
    return left


def create_sync(
    client: Client | None,
    model: object,
    prompt: object,
    *,
    messages: object,
    tools: object,
    stream: bool,
    stream_options: Mapping[str, Any] | None,
    use_cache: bool,
    max_retries: int | None,
    timeout: float | httpx.Timeout | None,
    other: Mapping[str, Any],
) -> ChatCompletion | ChatStream:
    """Check and send one chat call with a sync Client (contracts C1.2).

    ``client`` None means the default client at this time (D14, D15). The SDK takes it after
    the argument checks. The call blocks and returns the reply, or a ChatStream when ``stream``
    is True.

    The timeout counts the catalogue read and the compile.
    """

    source, build = _checked(
        model,
        prompt,
        messages=messages,
        tools=tools,
        stream=stream,
        stream_options=stream_options,
        use_cache=use_cache,
        max_retries=max_retries,
        timeout=timeout,
        other=other,
    )
    if client is None:
        # WHY at each call (MI-S20b): sf.configure() and sf.close() change the default client, as
        # for sf.classify.
        client = _default_client.default_client()
    # INVARIANT: a closed client raises its RuntimeError before a request and before the
    # catalogue load.
    client._require_open()
    max_tries, limit = _limits(client, max_retries, timeout)
    started = transport._clock()
    text = model_text(source, client._operator_catalog.load)
    call = build(text, max_tries, _time_left(limit, started))
    if stream:
        return open_chat_stream(client._engine_post_stream, client.engine_url, call)
    return send_chat(client._engine_post_stream, client.engine_url, call)


def create_async(
    client: AsyncClient,
    model: object,
    prompt: object,
    *,
    messages: object,
    tools: object,
    stream: bool,
    stream_options: Mapping[str, Any] | None,
    use_cache: bool,
    max_retries: int | None,
    timeout: float | httpx.Timeout | None,
    other: Mapping[str, Any],
) -> Coroutine[Any, Any, ChatCompletion | AsyncChatStream]:
    """Check one chat call and give the coroutine that sends it (contracts C1.2).

    WHY a coroutine from a plain def (C1.2, MI-24): each argument error and a closed client are
    raised by this call; only the catalogue, network and Engine errors come at the await.

    The timeout counts the catalogue read and the compile.
    """

    source, build = _checked(
        model,
        prompt,
        messages=messages,
        tools=tools,
        stream=stream,
        stream_options=stream_options,
        use_cache=use_cache,
        max_retries=max_retries,
        timeout=timeout,
        other=other,
    )
    client._require_open()
    return _create_async(
        client, source, build, stream=stream, max_retries=max_retries, timeout=timeout
    )


async def _create_async(
    client: AsyncClient,
    source: ModelSource,
    build: Callable[[str, int, float | None], ChatCall],
    *,
    stream: bool,
    max_retries: int | None,
    timeout: float | httpx.Timeout | None,
) -> ChatCompletion | AsyncChatStream:
    """The async half of create_async: the catalogue load, the compile and the send (C1.2)."""

    max_tries, limit = _limits(client, max_retries, timeout)
    started = transport._clock()
    text = await _resolve_async(client, source, limit)
    call = build(text, max_tries, _time_left(limit, started))
    if stream:
        return await open_chat_stream_async(client._engine_post_stream, client.engine_url, call)
    return await send_chat_async(client._engine_post_stream, client.engine_url, call)


async def _resolve_async(client: AsyncClient, source: ModelSource, limit: float | None) -> str:
    """The model text of an async call, stopped at the call limit (RR-S18)."""

    scope = asyncio.timeout(limit)
    try:
        async with scope:
            return await model_text_async(source, client._operator_catalog.load)
    except TimeoutError:
        if not scope.expired():
            raise
    raise client_timeout(new_trace_context().trace_id) from None


def endpoint_sync(client: Client | None, model: object) -> InferenceEndpoint:
    """The endpoint values of one model for another OpenAI client (contracts C1.5).

    ``client`` None means the default client at this time (D14, D15).
    """

    source = model_source(model)
    if client is None:
        client = _default_client.default_client()
    # INVARIANT: a closed client raises its RuntimeError before a request.
    client._require_open()
    hosted = _hosted(client.engine_url)
    if hosted:
        # WHY first (C1.5): the sign-in learns the audience of the token, so the catalogue
        # load and the headers below carry the token.
        client.login()
    text = model_text(source, client._operator_catalog.load)
    headers = client._engine_auth.websocket_headers() if hosted else {}
    return _endpoint(client.engine_url, text, headers)


def endpoint_async(client: AsyncClient, model: object) -> Coroutine[Any, Any, InferenceEndpoint]:
    """Give the coroutine of the endpoint values of one model (contracts C1.5).

    A model error and a closed client are raised by this call, before a coroutine exists (EB-S7).
    """

    source = model_source(model)
    client._require_open()
    return _endpoint_async(client, source)


async def _endpoint_async(client: AsyncClient, source: ModelSource) -> InferenceEndpoint:
    """The async half of endpoint_async: the sign-in, the compile and the headers."""

    hosted = _hosted(client.engine_url)
    if hosted:
        await client.login()
    model = await model_text_async(source, client._operator_catalog.load)
    headers = await client._engine_auth.websocket_headers_async() if hosted else {}
    return _endpoint(client.engine_url, model, headers)


def _hosted(engine_url: str) -> bool:
    """True for an https Engine, which is behind Cloudflare Access (C1.5).

    A local http Engine needs no sign-in and no auth header (EB-S2).
    """

    return urlsplit(engine_url).scheme == "https"


def _endpoint(engine_url: str, model: str, headers: Mapping[str, str]) -> InferenceEndpoint:
    """One InferenceEndpoint with a read-only copy of the headers (a snapshot, EB-S6)."""

    # WHY here: screamingface.inference imports this module, and the public class lives there.
    from screamingface.inference import InferenceEndpoint  # noqa: PLC0415

    # WHY /v1: the OpenAI client adds /chat/completions to its base_url, and the Engine route
    # is POST /v1/chat/completions (C2.1).
    return InferenceEndpoint(
        base_url=f"{engine_url}/v1", model=model, headers=MappingProxyType(dict(headers))
    )


__all__ = ["create_async", "create_sync", "endpoint_async", "endpoint_sync"]
