"""Chat calls through the lazy default Client: the module twin of ``client.chat`` (sf.chat).

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.1 and C1.2;
D15). ``sf.chat.completions.create(model=..., ...)`` and ``sf.chat.endpoint(model)`` work as
``sf.Client().chat``, with the default client at the time of each call, as sf.models does.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Literal, overload

from screamingface._inference.calls import create_sync, endpoint_sync
from screamingface.chat_completion import ChatCompletion, ChatMessage, ChatStream
from screamingface.inference import InferenceEndpoint

if TYPE_CHECKING:
    import httpx

    from screamingface.recipe import Recipe
    from screamingface.url4 import Url4


class _DefaultCompletions:
    """``sf.chat.completions``: Completions.create on the default client (D15)."""

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
        """Send one chat call with the default client and give its reply (contracts C1.2).

        The arguments and the result are those of ``sf.Client().chat.completions.create``.
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

        # WHY None: create_sync takes the default client after the argument checks (D15), so
        # sf.configure() and sf.close() apply.
        # AIDEV-NOTE: call the shared function directly (no helper between): the warning names the
        # line of the caller.
        return create_sync(
            None,
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


completions = _DefaultCompletions()


def endpoint(model: Recipe | Url4 | str) -> InferenceEndpoint:
    """Give the endpoint values of one model through the default client (contracts C1.5).

    See ``sf.Client().chat.endpoint`` for the sign-in and the snapshot rule.
    """

    return endpoint_sync(None, model)


__all__ = ["completions", "endpoint"]
