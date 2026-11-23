"""Call a recipe, a URL4 or a gateway model with the OpenAI client shape (sf.InferenceClient).

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.1, C1.2 and
C1.5). The path ``client.chat.completions.create(model=..., messages=...)`` is the path of the
OpenAI SDK, so code written for it needs only a new client line (D11, D12). One class and one method
name serve the sync and the async client. Typed overloads on the client type and on the value of
``stream`` give the result type (ans:Q7).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, overload
from urllib.parse import urlsplit

from screamingface import _default_client
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
)
from screamingface._inference.transport import (
    open_chat_stream,
    open_chat_stream_async,
    send_chat,
    send_chat_async,
)
from screamingface.chat_completion import AsyncChatStream, ChatCompletion, ChatStream

# WHY a run-time import: U4 checks the client type with isinstance, and reading
# ClientT.__constraints__ needs the names.
from screamingface.client import AsyncClient, Client

if TYPE_CHECKING:
    from screamingface.recipe import Recipe
    from screamingface.url4 import Url4


@dataclass(frozen=True, slots=True, kw_only=True)
class InferenceEndpoint:
    """The values that another OpenAI client needs to call this model (contracts C1.5).

    The values are a snapshot. On a hosted Engine the Access token in ``headers`` expires. Then
    call ``endpoint()`` again.
    """

    base_url: str
    model: str
    # WHY hash=False: a read-only mapping has no hash. Equal endpoints still have equal hashes,
    # because the hash uses base_url and model.
    headers: Mapping[str, str] = field(hash=False)

    def __repr__(self) -> str:
        # INVARIANT (EB-S4): a header value can be an Access token. The text form shows the header
        # names and hides each value. str() uses this text too.
        names = ", ".join(f"{name!r}: '***'" for name in self.headers)
        return (
            f"InferenceEndpoint(base_url={self.base_url!r}, model={self.model!r}, "
            f"headers={{{names}}})"
        )


class Completions[ClientT: (Client, AsyncClient)]:
    """The ``chat.completions`` namespace of an InferenceClient, as in the OpenAI SDK (C1.2)."""

    def __init__(self, owner: InferenceClient[ClientT]) -> None:
        self._owner = owner

    @overload
    def create(
        self: Completions[Client],
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: Literal[False] = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int = 0,
        timeout: float | None = None,
        **other: Any,
    ) -> ChatCompletion: ...
    @overload
    def create(
        self: Completions[Client],
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: Literal[True],
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int = 0,
        timeout: float | None = None,
        **other: Any,
    ) -> ChatStream: ...
    @overload
    def create(
        self: Completions[Client],
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: bool,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int = 0,
        timeout: float | None = None,
        **other: Any,
    ) -> ChatCompletion | ChatStream: ...
    @overload
    def create(
        self: Completions[AsyncClient],
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: Literal[False] = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int = 0,
        timeout: float | None = None,
        **other: Any,
    ) -> Coroutine[Any, Any, ChatCompletion]: ...
    @overload
    def create(
        self: Completions[AsyncClient],
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: Literal[True],
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int = 0,
        timeout: float | None = None,
        **other: Any,
    ) -> Coroutine[Any, Any, AsyncChatStream]: ...
    @overload
    def create(
        self: Completions[AsyncClient],
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: bool,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int = 0,
        timeout: float | None = None,
        **other: Any,
    ) -> Coroutine[Any, Any, ChatCompletion | AsyncChatStream]: ...
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: bool = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int = 0,
        timeout: float | None = None,
        **other: Any,
    ) -> ChatCompletion | ChatStream | Coroutine[Any, Any, ChatCompletion | AsyncChatStream]:
        """Send one chat call and give its reply (contracts C1.2).

        ``model`` is a recipe, a URL4 or a gateway model id, as for the constructor. It replaces
        the model of the client for this call only. With no model here and no model on the client,
        the call raises TypeError. ``prompt`` is a short form of one user message; it is not in
        the OpenAI SDK, which takes ``messages`` only.

        With a sync Client the call blocks and returns the reply, or a ChatStream when
        ``stream`` is True. With an AsyncClient the call returns a coroutine.

        With stream=True and a sync Client, the call returns a ChatStream that is open at its first
        chunk. With an AsyncClient, this call raises each argument error before a coroutine exists;
        the await raises the network and Engine errors.

        Raises:
            TypeError: an argument has the wrong type, or there is no model.
            ValueError: an argument has a wrong value.
            PlanningError: the model or a parameter is refused.
            AuthenticationError: the Engine rejects the caller.
            EngineCapabilityError: the Engine lacks the chat route.
            ExecutionError: the run fails, times out or gives a wrong answer.
            EngineUnavailableError: the Engine cannot be reached.
        """

        source = self._owner._source_for(model)
        messages_list = chat_messages(prompt, messages)
        tools_list = chat_tools(tools)
        check_options(
            stream=stream,
            stream_options=stream_options,
            use_cache=use_cache,
            max_retries=max_retries,
            timeout=timeout,
        )
        # WHY directly here: check_other warns with stacklevel=3, so the warning names the line
        # of the caller.
        check_other(other)
        client = self._owner._call_client()
        # INVARIANT: a closed client raises its RuntimeError before a request, before the catalogue
        # load and before a coroutine exists.
        client._require_open()
        build = partial(
            chat_call,
            messages=messages_list,
            tools=tools_list,
            stream=stream,
            stream_options=stream_options,
            use_cache=use_cache,
            max_retries=max_retries,
            timeout=timeout,
        )
        if isinstance(client, AsyncClient):
            # WHY a coroutine from a plain def (C1.2, MI-24): each argument error above is raised
            # by this call; only the catalogue, network and Engine errors come at the await.
            return _create_async(client, source, build, stream=stream)
        call = build(model_text(source, client._operator_catalog.load))
        if stream:
            return open_chat_stream(client._engine_post_stream, client.engine_url, call)
        return send_chat(client._engine_post_stream, client.engine_url, call)


class Chat[ClientT: (Client, AsyncClient)]:
    """The ``chat`` namespace of an InferenceClient (contracts C1.2)."""

    completions: Completions[ClientT]

    def __init__(self, owner: InferenceClient[ClientT]) -> None:
        self.completions = Completions(owner)


async def _create_async(
    client: AsyncClient,
    source: ModelSource,
    build: Callable[[str], ChatCall],
    *,
    stream: bool,
) -> ChatCompletion | AsyncChatStream:
    """The async half of Completions.create: the catalogue load, the compile and the send (C1.2)."""

    call = build(await model_text_async(source, client._operator_catalog.load))
    if stream:
        return await open_chat_stream_async(client._engine_post_stream, client.engine_url, call)
    return await send_chat_async(client._engine_post_stream, client.engine_url, call)


class InferenceClient[ClientT: (Client, AsyncClient)]:
    """A chat client for recipes, URL4 and gateway model ids, with the shape of the OpenAI client.

    ``model`` is optional. A model given here is the default of each call; a call can give its
    own with ``create(model=...)``, as with the OpenAI client. With no client, or with a sync
    Client, each call blocks and returns its result. With an AsyncClient, each call returns a
    coroutine. The object keeps no conversation.
    """

    chat: Chat[ClientT]

    @overload
    def __init__(
        self: InferenceClient[Client],
        model: Recipe | Url4 | str | None = None,
        *,
        client: Client | None = None,
    ) -> None: ...
    @overload
    def __init__(
        self: InferenceClient[AsyncClient],
        model: Recipe | Url4 | str | None = None,
        *,
        client: AsyncClient,
    ) -> None: ...
    def __init__(
        self,
        model: Recipe | Url4 | str | None = None,
        *,
        client: Client | AsyncClient | None = None,
    ) -> None:
        # INVARIANT: the constructor sends no request (P2); a recipe with a reducer compiles at
        # each call.
        if client is not None and not isinstance(client, Client | AsyncClient):
            raise TypeError("client must be a sf.Client, a sf.AsyncClient or None")
        # WHY None (D12): as the OpenAI client, the object can have no model; each call then gives
        # one with create(model=...).
        self._source: ModelSource | None = None if model is None else model_source(model)
        self._client = client
        self.chat = Chat(self)

    def _source_for(self, model: object) -> ModelSource:
        """The model of one call: the model of the call, else the model of the client (D12)."""

        if model is not None:
            return model_source(model)
        if self._source is None:
            raise TypeError("give a model: sf.InferenceClient(model) or create(model=...)")
        return self._source

    def _call_client(self) -> Client | AsyncClient:
        """The client of one call: the client of the object, or the default client at this time."""

        if self._client is not None:
            return self._client
        # WHY at each call (MI-S20b): sf.configure() and sf.close() change the default client, as
        # for sf.classify.
        return _default_client.default_client()

    @overload
    def endpoint(
        self: InferenceClient[Client], model: Recipe | Url4 | str | None = None
    ) -> InferenceEndpoint: ...
    @overload
    def endpoint(
        self: InferenceClient[AsyncClient], model: Recipe | Url4 | str | None = None
    ) -> Coroutine[Any, Any, InferenceEndpoint]: ...
    def endpoint(
        self, model: Recipe | Url4 | str | None = None
    ) -> InferenceEndpoint | Coroutine[Any, Any, InferenceEndpoint]:
        """Give the URL, the model text and the headers for another OpenAI client (C1.5).

        ``model`` follows the rule of ``create(model=...)``: it replaces the model of the client.

        On an https Engine this call signs in first with ``Client.login()``. That call returns at
        once when a usable token exists. With no usable token, it starts the browser sign-in and
        can wait up to 300 seconds. In a script with no browser, set SCREAMINGFACE_ACCESS_TOKEN or
        call client.login() first. The values are a snapshot: when the Access token expires, call
        ``endpoint()`` again. With an AsyncClient the call returns a coroutine.

        Raises:
            TypeError: there is no model.
            RuntimeError: the client is closed.
            AuthenticationError: the sign-in fails.
            ValueError: the recipe does not compile.
            PlanningError: the recipe does not compile.
            EngineCapabilityError: the operator catalogue cannot load.
            EngineUnavailableError: the Engine cannot be reached.
        """

        source = self._source_for(model)
        client = self._call_client()
        # INVARIANT: a closed client raises its RuntimeError before a request and before a
        # coroutine exists.
        client._require_open()
        if isinstance(client, AsyncClient):
            # WHY a coroutine from a plain def (EB-S7): the same form as Completions.create.
            return _endpoint_async(client, source)
        hosted = _hosted(client.engine_url)
        if hosted:
            # WHY first (C1.5): the sign-in learns the audience of the token, so the catalogue
            # load and the headers below carry the token.
            client.login()
        text = model_text(source, client._operator_catalog.load)
        headers = client._engine_auth.websocket_headers() if hosted else {}
        return _endpoint(client.engine_url, text, headers)


async def _endpoint_async(client: AsyncClient, source: ModelSource) -> InferenceEndpoint:
    """The async half of InferenceClient.endpoint: the sign-in, the compile and the headers."""

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

    # WHY /v1: the OpenAI client adds /chat/completions to its base_url, and the Engine route
    # is POST /v1/chat/completions (C2.1).
    return InferenceEndpoint(
        base_url=f"{engine_url}/v1", model=model, headers=MappingProxyType(dict(headers))
    )
