"""Physical upstream send admissions for one Gateway request (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — every non-streaming chat and classification response
# carries `X-AIGW-Upstream-Attempts`, the number of HTTP requests the Gateway admitted upstream to
# produce it. The Engine records that count as the call's physical attempts.
# INVARIANT: one mutable counter per request, bound once by the middleware before routing; a send
# hook only mutates it. A `ContextVar` rebound inside a task would be lost at a
# `BaseHTTPMiddleware` task boundary; a mutation of the object every task shares is not.
# INVARIANT: the hook is total. It can never raise, so it can never become an error LiteLLM
# resends on.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final, Literal

import httpx

HEADER = "x-aigw-upstream-attempts"

# The two ways a provider's inference sends can be observed. Every provider declares one
# (`ProviderPluginCore.upstream_send_path`); a fitness test refuses a provider that declares none.
# INVARIANT: `litellm_http` means LiteLLM sends through the `client` the Gateway injects; the chat
# route injects an observed handler for it. `plugin_http` means the plugin's own HTTP clients carry
# `record_send` on their request hooks.
LITELLM_HTTP: Final = "litellm_http"
PLUGIN_HTTP: Final = "plugin_http"
UpstreamSendPath = Literal["litellm_http", "plugin_http"]


class UpstreamAttempts:
    """The physical sends admitted for one request; starts at ``0``."""

    __slots__ = ("count",)

    def __init__(self) -> None:
        self.count = 0


_CURRENT: ContextVar[UpstreamAttempts | None] = ContextVar("aigw_upstream_attempts", default=None)


@contextmanager
def bound_attempts(counter: UpstreamAttempts) -> Iterator[UpstreamAttempts]:
    """Count every observed send made in this context, and in tasks it starts, into ``counter``."""
    token = _CURRENT.set(counter)
    try:
        yield counter
    finally:
        _CURRENT.reset(token)


async def record_send(request: httpx.Request) -> None:
    """An httpx request hook: one physical send was admitted.

    # WHY a request hook: httpx runs it once per request it is about to send, which includes each
    # redirect hop and each resend on a replacement client, and runs nothing for a request that is
    # refused before it is built. Outside any bound counter it does nothing.
    """
    del request
    counter = _CURRENT.get()
    if counter is not None:
        counter.count += 1


def observe(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Put ``record_send`` first on ``client``'s request hooks, once, and return the client."""
    hooks = client.event_hooks
    if record_send not in hooks["request"]:
        client.event_hooks = {**hooks, "request": [record_send, *hooks["request"]]}
    return client


def attempt_event_hooks() -> dict[str, list[Any]]:
    """The hooks of a LiteLLM handler that observes sends and accounts for nothing."""
    return {"request": [record_send], "response": []}


def with_observed_litellm_client(
    body: dict[str, Any], *, plugin: object, handler: object | None
) -> dict[str, Any]:
    """``body`` with the observed LiteLLM handler as ``client``, when the provider sends through it.

    # INVARIANT: a fresh dict when it injects; the caller's body is the one the cache keyed.
    # INVARIANT: an already injected client wins. The usage-accounting handler counts too, so a
    # second injection would only replace one observer with another.
    """
    if "client" in body or handler is None:
        return body
    if getattr(plugin, "upstream_send_path", None) != LITELLM_HTTP:
        return body
    return {**body, "client": handler}
