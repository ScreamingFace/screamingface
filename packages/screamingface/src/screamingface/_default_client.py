"""One lazily constructed synchronous module-level Client."""

from __future__ import annotations

import os
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal, cast, overload

from screamingface.client import DEFAULT_ENGINE_URL, DEFAULT_SCOREBOARD_URL, Client

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from screamingface._ui.connections import ConnectionPanel
    from screamingface.connections import Connection, OAuthFlow
    from screamingface.events import Event
    from screamingface.recipe import Recipe
    from screamingface.report import Report

_client: Client | None = None
_lock = Lock()


def default_client() -> Client:
    """Return the process-wide Client, constructing it on first use.

    Engine selection precedence (OME-998):

    1. `SCREAMINGFACE_ENGINE_URL` — explicit always wins, silently.
    2. A running, liveness-checked local `screamingface up` stack — announced with an
       info line naming the chosen URL and the override env var.
    3. The hosted default — silent, unchanged behavior.
    """

    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            engine_url = os.environ.get("SCREAMINGFACE_ENGINE_URL")
            scoreboard_url = os.environ.get("SCREAMINGFACE_SCOREBOARD_URL")
            if engine_url is None:
                from screamingface._runtime.detect import running_local_services

                local = running_local_services()
                if local is not None:
                    engine_url = local["engine"]
                    # WHY both URLs: `screamingface up` tells users to export BOTH env
                    # vars; adopting only the engine would invent a hybrid state
                    # (local engine + hosted leaderboard) the documented flow never
                    # produces. Each env var individually keeps precedence.
                    if scoreboard_url is None:
                        scoreboard_url = local["scoreboard"]
                    print(
                        f"connected to the local stack at {engine_url} — "
                        "set SCREAMINGFACE_ENGINE_URL to override"
                    )
            _client = Client(
                engine_url=engine_url if engine_url is not None else DEFAULT_ENGINE_URL,
                scoreboard_url=(
                    scoreboard_url if scoreboard_url is not None else DEFAULT_SCOREBOARD_URL
                ),
            )
    return _client


def configure(
    *,
    engine_url: str = DEFAULT_ENGINE_URL,
    scoreboard_url: str = DEFAULT_SCOREBOARD_URL,
) -> Client:
    """Replace the process-wide Client used by module-level convenience functions."""

    global _client
    replacement = Client(engine_url=engine_url, scoreboard_url=scoreboard_url)
    with _lock:
        previous = _client
        _client = replacement
    if previous is not None:
        previous.close()
    return replacement


def close() -> None:
    """Close and forget the process-wide Client, if it has been created."""

    global _client
    with _lock:
        previous = _client
        _client = None
    if previous is not None:
        previous.close()


@overload
def evaluate(
    candidates: str,
    *,
    benchmark: None = None,
    limit: None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
) -> Report: ...


@overload
def evaluate(
    candidates: Recipe | Sequence[Recipe],
    *,
    benchmark: str,
    limit: int | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
) -> Report: ...


def evaluate(
    candidates: Recipe | Sequence[Recipe] | str,
    *,
    benchmark: str | None = None,
    limit: int | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
) -> Report:
    """Evaluate Recipes or a complete URL4 through the lazy default Client."""

    client = default_client()
    return cast(Any, client).evaluate(
        candidates,
        benchmark=benchmark,
        limit=limit,
        on_event=on_event,
        progress=progress,
    )


@overload
def connect(
    provider: None = None,
    *,
    api_key: None = None,
    method: None = None,
) -> ConnectionPanel: ...


@overload
def connect(
    provider: str,
    *,
    api_key: str,
    method: Literal["api_key"] | None = None,
) -> Connection: ...


@overload
def connect(
    provider: str,
    *,
    api_key: None = None,
    method: Literal["oauth"],
) -> OAuthFlow: ...


def connect(
    provider: str | None = None,
    *,
    api_key: str | None = None,
    method: Literal["api_key", "oauth"] | None = None,
) -> Connection | ConnectionPanel | OAuthFlow:
    """Open the provider panel or connect through the lazy default Client."""

    if provider is None:
        if api_key is not None or method is not None:
            raise TypeError("provider is required when api_key or method is supplied")
        from screamingface._ui.connections import ConnectionPanel

        return ConnectionPanel(default_client())
    client = default_client()
    if api_key is not None:
        if method == "oauth":
            raise ValueError("api_key cannot be combined with OAuth")
        result = client.connect(provider, api_key=api_key, method=method)
    elif method == "api_key":
        raise ValueError("api_key is required for API-key authentication")
    elif method == "oauth":
        result = client.connect(provider, method="oauth")
    else:
        raise ValueError("api_key is required unless method='oauth' is selected")
    return result


def disconnect(provider: str) -> Connection:
    """Disconnect a provider through the lazy default Client."""

    return default_client().disconnect(provider)


__all__ = ["close", "configure", "connect", "disconnect", "evaluate"]
