"""Call a recipe, a URL4 or a gateway model with the call path of the OpenAI client.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.1, C1.2 and
C1.5; overview §5.5, D13 to D17). There is no client class for chat. ``client.chat`` (Chat,
AsyncChat) is a namespace of sf.Client and sf.AsyncClient, ``recipe.chat`` (RecipeChat) is a
property of each recipe, and the module ``sf.chat`` is the twin of ``client.chat`` for the
default client. Each create method and each endpoint method calls one shared function of
screamingface._inference.calls, so the checks and the send are the same on each surface.
"""

from __future__ import annotations

from collections.abc import Coroutine, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, overload

from screamingface._inference.calls import create_async, create_sync, endpoint_async, endpoint_sync
from screamingface.chat_completion import (
    AsyncChatStream,
    ChatCompletion,
    ChatMessage,
    ChatStream,
)

if TYPE_CHECKING:
    import httpx

    from screamingface.client import AsyncClient, Client
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


class Completions:
    """``sf.Client().chat.completions``: the OpenAI call path on one sync client (C1.2, D13)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: Literal[False] = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> ChatCompletion: ...
    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: Literal[True],
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> ChatStream: ...
    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: bool,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> ChatCompletion | ChatStream: ...
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: bool = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> ChatCompletion | ChatStream:
        """Send one chat call and give its reply (contracts C1.2).

        ``model`` is a recipe, a sf.Url4, URL4 text or a gateway model id. It is a required
        keyword, as in the OpenAI client. ``prompt`` is a short form of one user message; it is
        not in the OpenAI SDK, which takes ``messages`` only. With stream=True the call returns
        a ChatStream that is open at its first chunk.
        max_retries and timeout default to the values of the client.

        Raises:
            TypeError: an argument has the wrong type, or a keyword is unknown.
            ValueError: an argument has a wrong value.
            PlanningError: the model or a parameter is refused.
            AuthenticationError: the Engine rejects the caller.
            EngineCapabilityError: the Engine lacks the chat route.
            ExecutionError: the run fails, times out or gives a wrong answer.
            EngineUnavailableError: the Engine cannot be reached.
        """

        # AIDEV-NOTE: call the shared function directly (no helper between): the warning names the
        # line of the caller.
        return create_sync(
            self._client,
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


class AsyncCompletions:
    """``sf.AsyncClient().chat.completions``: the OpenAI call path on one async client (C1.2)."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: Literal[False] = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> Coroutine[Any, Any, ChatCompletion]: ...
    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: Literal[True],
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> Coroutine[Any, Any, AsyncChatStream]: ...
    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: bool,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> Coroutine[Any, Any, ChatCompletion | AsyncChatStream]: ...
    def create(
        self,
        prompt: str | None = None,
        *,
        model: Recipe | Url4 | str,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: bool = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> Coroutine[Any, Any, ChatCompletion | AsyncChatStream]:
        """Send one chat call and give a coroutine of its reply (contracts C1.2).

        This is a plain def: each argument error is raised by this call, before a coroutine
        exists (MI-24). The await raises the network and Engine errors. The rules of
        ``model`` are those of Completions.create.
        max_retries and timeout default to the values of the client.

        Raises:
            TypeError: an argument has the wrong type, or a keyword is unknown.
            ValueError: an argument has a wrong value.
            PlanningError: the model or a parameter is refused.
            AuthenticationError: the Engine rejects the caller.
            EngineCapabilityError: the Engine lacks the chat route.
            ExecutionError: the run fails, times out or gives a wrong answer.
            EngineUnavailableError: the Engine cannot be reached.
        """

        # AIDEV-NOTE: call the shared function directly (no helper between): the warning names the
        # line of the caller.
        return create_async(
            self._client,
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


class Chat:
    """``sf.Client().chat`` (contracts C1.1, D13). It keeps its client and no other state."""

    completions: Completions

    def __init__(self, client: Client) -> None:
        self._client = client
        self.completions = Completions(client)

    def endpoint(self, model: Recipe | Url4 | str) -> InferenceEndpoint:
        """Give the URL, the model text and the headers for another OpenAI client (C1.5).

        On an https Engine this call signs in first with ``Client.login()``. That call returns at
        once when a usable token exists. With no usable token, it starts the browser sign-in and
        can wait up to 300 seconds. In a script with no browser, set SCREAMINGFACE_ACCESS_TOKEN or
        call client.login() first. The values are a snapshot: when the Access token expires, call
        ``endpoint()`` again.

        Raises:
            TypeError: the model has the wrong type.
            RuntimeError: the client is closed.
            AuthenticationError: the sign-in fails.
            ValueError: the recipe does not compile.
            PlanningError: the recipe does not compile.
            EngineCapabilityError: the operator catalogue cannot load.
            EngineUnavailableError: the Engine cannot be reached.
        """

        return endpoint_sync(self._client, model)


class AsyncChat:
    """``sf.AsyncClient().chat`` (contracts C1.1, D13). It keeps its client and no other state."""

    completions: AsyncCompletions

    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self.completions = AsyncCompletions(client)

    def endpoint(self, model: Recipe | Url4 | str) -> Coroutine[Any, Any, InferenceEndpoint]:
        """Give a coroutine of the endpoint values for another OpenAI client (C1.5).

        This is a plain def: a model error and a closed client are raised by this call, before
        a coroutine exists (EB-S7). See Chat.endpoint for the sign-in and the snapshot rule.
        """

        return endpoint_async(self._client, model)


class RecipeCompletions:
    """``recipe.chat.completions``: the OpenAI call path for one recipe (contracts C1.1, D14).

    Each call takes the default client at that time, so sf.configure() and sf.close() apply. It
    is sync only; an async caller uses ``aclient.chat.completions.create(model=recipe, ...)``.
    """

    def __init__(self, recipe: Recipe) -> None:
        self._recipe = recipe

    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: Literal[False] = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> ChatCompletion: ...
    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: Literal[True],
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> ChatStream: ...
    @overload
    def create(
        self,
        prompt: str | None = None,
        *,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: bool,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> ChatCompletion | ChatStream: ...
    def create(
        self,
        prompt: str | None = None,
        *,
        messages: Iterable[Mapping[str, Any] | ChatMessage] | None = None,
        tools: Iterable[Mapping[str, Any]] | None = None,
        stream: bool = False,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        **other: Any,
    ) -> ChatCompletion | ChatStream:
        """Send one chat call to the recipe through the default client (contracts C1.2).

        The recipe is the model, so this method has no ``model`` parameter: a ``model=``
        keyword raises TypeError. A recipe with a corrective loop raises PlanningError
        (recipe_not_supported) here, before a request.
        max_retries and timeout default to the values of the client.

        Raises:
            TypeError: an argument has the wrong type, or a keyword is unknown.
            ValueError: an argument has a wrong value.
            PlanningError: the model or a parameter is refused.
            AuthenticationError: the Engine rejects the caller.
            EngineCapabilityError: the Engine lacks the chat route.
            ExecutionError: the run fails, times out or gives a wrong answer.
            EngineUnavailableError: the Engine cannot be reached.
        """

        # WHY None: create_sync takes the default client after the argument checks (D14).
        # AIDEV-NOTE: call the shared function directly (no helper between): the warning names the
        # line of the caller.
        return create_sync(
            None,
            self._recipe,
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


class RecipeChat:
    """``recipe.chat`` (contracts C1.1, D14): a small object that keeps only its recipe.

    The property Recipe.chat makes a new one at each access. The access compiles nothing, sends
    no request and raises nothing.
    """

    completions: RecipeCompletions

    def __init__(self, recipe: Recipe) -> None:
        self._recipe = recipe
        self.completions = RecipeCompletions(recipe)

    def endpoint(self) -> InferenceEndpoint:
        """Give the endpoint values of the recipe through the default client (C1.5).

        See Chat.endpoint for the sign-in and the snapshot rule.

        Raises:
            TypeError: the model has the wrong type.
            RuntimeError: the client is closed.
            AuthenticationError: the sign-in fails.
            ValueError: the recipe does not compile.
            PlanningError: the recipe does not compile.
            EngineCapabilityError: the operator catalogue cannot load.
            EngineUnavailableError: the Engine cannot be reached.
        """

        return endpoint_sync(None, self._recipe)


__all__ = [
    "AsyncChat",
    "AsyncCompletions",
    "Chat",
    "Completions",
    "InferenceEndpoint",
    "RecipeChat",
    "RecipeCompletions",
]
