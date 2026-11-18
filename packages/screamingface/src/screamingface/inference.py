"""Call a recipe, a URL4 or a gateway model as an OpenAI-style chat model (sf.ModelInference).

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.1, C1.2 and
C1.5). One class and one method name serve the sync and the async client. Typed overloads on the
client type and on the value of ``stream`` give the result type (ans:Q7).
"""

from __future__ import annotations

from collections.abc import Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, overload

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

    AIDEV-NOTE: unit U6 adds a repr that shows the header names and hides each value. Until
    then, the repr does not show the headers.
    """

    base_url: str
    model: str
    headers: Mapping[str, str] = field(repr=False)


class Chat[ClientT: (Client, AsyncClient)]:
    """The ``chat`` namespace of a ModelInference (contracts C1.2)."""

    def __init__(self, owner: ModelInference[ClientT]) -> None:
        self._owner = owner

    @overload
    def complete(
        self: Chat[Client],
        prompt: str | None = None,
        *,
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
    def complete(
        self: Chat[Client],
        prompt: str | None = None,
        *,
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
    def complete(
        self: Chat[Client],
        prompt: str | None = None,
        *,
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
    def complete(
        self: Chat[AsyncClient],
        prompt: str | None = None,
        *,
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
    def complete(
        self: Chat[AsyncClient],
        prompt: str | None = None,
        *,
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
    def complete(
        self: Chat[AsyncClient],
        prompt: str | None = None,
        *,
        messages: Sequence[Mapping[str, Any]] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: bool,
        stream_options: Mapping[str, Any] | None = None,
        use_cache: bool = True,
        max_retries: int = 0,
        timeout: float | None = None,
        **other: Any,
    ) -> Coroutine[Any, Any, ChatCompletion | AsyncChatStream]: ...
    def complete(
        self,
        prompt: str | None = None,
        *,
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

        With a sync Client the call blocks and returns the reply, or a ChatStream when
        ``stream`` is True. With an AsyncClient the call returns a coroutine.
        """

        # AIDEV-NOTE: unit U4 (sync) and unit U5 (streams, async) fill this body.
        raise NotImplementedError("ModelInference.chat.complete is not available yet")


class ModelInference[ClientT: (Client, AsyncClient)]:
    """A recipe, a URL4 or a gateway model id that you call as a chat model.

    With no client, or with a sync Client, each call blocks and returns its result. With an
    AsyncClient, each call returns a coroutine. The object keeps no conversation.
    """

    chat: Chat[ClientT]

    @overload
    def __init__(
        self: ModelInference[Client],
        model: Recipe | Url4 | str,
        *,
        client: Client | None = None,
    ) -> None: ...
    @overload
    def __init__(
        self: ModelInference[AsyncClient],
        model: Recipe | Url4 | str,
        *,
        client: AsyncClient,
    ) -> None: ...
    def __init__(
        self,
        model: Recipe | Url4 | str,
        *,
        client: Client | AsyncClient | None = None,
    ) -> None:
        # AIDEV-NOTE: unit U4 adds the model rule (P1, P14), the type checks and the compile
        # step (P2, P17). The constructor sends no request (P2).
        self._model = model
        self._client = client
        self.chat = Chat(self)

    @overload
    def endpoint(self: ModelInference[Client]) -> InferenceEndpoint: ...
    @overload
    def endpoint(self: ModelInference[AsyncClient]) -> Coroutine[Any, Any, InferenceEndpoint]: ...
    def endpoint(self) -> InferenceEndpoint | Coroutine[Any, Any, InferenceEndpoint]:
        """Give the URL, the model text and the headers for another OpenAI client (C1.5)."""

        # AIDEV-NOTE: unit U6 fills this body.
        raise NotImplementedError("ModelInference.endpoint is not available yet")
