"""One lazily constructed synchronous module-level Client."""

from __future__ import annotations

import os
from threading import Lock
from typing import TYPE_CHECKING, Literal, overload
from urllib.parse import urlsplit

from screamingface._client_connections import _engine_origin
from screamingface.client import (
    DEFAULT_ENGINE_URL,
    DEFAULT_SCOREBOARD_URL,
    Client,
    _evaluation_candidates,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from uuid import UUID

    from screamingface._ui.connections import ConnectionPanel
    from screamingface.connections import Connection, OAuthFlow
    from screamingface.events import Event
    from screamingface.recipe import Recipe
    from screamingface.report import Report

_client: Client | None = None
_lock = Lock()


_SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443}


def _comparable_origin(engine_url: str) -> tuple[str, str, int]:
    """``(scheme, host, port)`` of an Engine origin, spelling-normalized for equality.

    WHY: `_engine_origin` keeps the caller's spelling, but scheme and host are
    case-insensitive and a scheme's default port is the same origin —
    `HTTPS://FUSION.SCREAMINGFACE.AI:443/` IS the hosted Engine.
    """

    parts = urlsplit(_engine_origin(engine_url))
    scheme = parts.scheme.casefold()
    port = parts.port if parts.port is not None else _SCHEME_DEFAULT_PORTS[scheme]
    return scheme, (parts.hostname or "").casefold(), port


def _paired_scoreboard(engine_url: str, scoreboard_url: str | None, *, hint: str) -> str:
    """The Scoreboard for ``engine_url``: the explicit one, else the hosted default for the
    hosted Engine, else refuse.

    WHY refuse rather than default: a local or preview Engine paired with the hosted
    Scoreboard publishes that Engine's scores to the public leaderboard (e2e workbench spec
    §1). The pairing must be stated, never inferred.
    """

    if scoreboard_url is not None:
        return scoreboard_url
    if _comparable_origin(engine_url) == _comparable_origin(DEFAULT_ENGINE_URL):
        return DEFAULT_SCOREBOARD_URL
    raise ValueError(
        f"engine_url {engine_url!r} is not the hosted Engine, so its Scoreboard must be "
        f"named too: {hint}"
    )


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
            resolved_engine = engine_url if engine_url is not None else DEFAULT_ENGINE_URL
            _client = Client(
                engine_url=resolved_engine,
                scoreboard_url=_paired_scoreboard(
                    resolved_engine,
                    scoreboard_url,
                    hint="set SCREAMINGFACE_SCOREBOARD_URL alongside SCREAMINGFACE_ENGINE_URL",
                ),
            )
    return _client


def configure(
    *,
    engine_url: str = DEFAULT_ENGINE_URL,
    scoreboard_url: str | None = None,
) -> Client:
    """Replace the process-wide Client used by module-level convenience functions.

    A non-default ``engine_url`` needs an explicit ``scoreboard_url``; see
    ``_paired_scoreboard``. A refused call leaves the previous Client installed and open.
    """

    global _client
    # INVARIANT: validate before the swap — a refused configure never closes the old Client.
    paired = _paired_scoreboard(engine_url, scoreboard_url, hint="pass scoreboard_url=...")
    replacement = Client(engine_url=engine_url, scoreboard_url=paired)
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
    answer_seed: int | None = None,
    capture: bool = True,
) -> Report: ...


@overload
def evaluate(
    candidates: Recipe | Sequence[Recipe],
    *,
    benchmark: str,
    limit: int | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
    answer_seed: int | None = None,
    capture: bool = True,
) -> Report: ...


@overload
def evaluate(
    *,
    pinned_cache: str,
    score_id: UUID | str | None = None,
    url4: str | None = None,
    answer_seed: int | None = None,
    record_reproduction: bool = True,
    limit: int | None = None,
    capture: Literal[False] | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
) -> Report: ...


@overload
def evaluate(
    *,
    score_id: UUID | str,
    pinned_cache: str | None = None,
    url4: str | None = None,
    answer_seed: int | None = None,
    record_reproduction: bool = True,
    limit: int | None = None,
    capture: Literal[False] | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
) -> Report: ...


def evaluate(
    candidates: Recipe | Sequence[Recipe] | str | None = None,
    *,
    benchmark: str | None = None,
    limit: int | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
    answer_seed: int | None = None,
    capture: bool | None = None,
    pinned_cache: str | None = None,
    score_id: UUID | str | None = None,
    url4: str | None = None,
    record_reproduction: bool = True,
) -> Report:
    """Evaluate Recipes or a complete URL4 through the lazy default Client.

    INVARIANT: this wrapper is a pass-through, never a narrower door — every option
    `Client.evaluate` accepts is reachable here too. It is the call every `examples/*.ipynb`
    uses, so an option missing here is an option the notebook audience cannot reach at all
    (OME-1227: `answer_seed` shipped on the Client and stayed unreachable from `sf.evaluate`).
    Validation stays with the Client, which refuses a bad seed before any token is minted.
    """

    client = default_client()
    if pinned_cache is not None or score_id is not None:
        # The Client checks the replay options; this door passes everything through.
        return client._evaluate_replay(
            candidates=candidates,
            benchmark=benchmark,
            limit=limit,
            capture=capture,
            pinned_cache=pinned_cache,
            score_id=score_id,
            url4=url4,
            answer_seed=answer_seed,
            record_reproduction=record_reproduction,
            on_event=on_event,
            progress=progress,
        )
    # One home for these checks: the Client's (review fix, no third copy here).
    candidates = _evaluation_candidates(candidates, url4, record_reproduction)
    capture = True if capture is None else capture
    if isinstance(candidates, str):
        if benchmark is not None:
            raise TypeError("benchmark must not be passed when evaluating a complete URL4")
        if limit is not None:
            raise TypeError("limit must not be passed when evaluating a complete URL4")
        return client.evaluate(
            candidates,
            on_event=on_event,
            progress=progress,
            answer_seed=answer_seed,
            capture=capture,
        )
    if benchmark is None:
        raise TypeError("benchmark is required when evaluating Recipes")
    return client.evaluate(
        candidates,
        benchmark=benchmark,
        limit=limit,
        on_event=on_event,
        progress=progress,
        answer_seed=answer_seed,
        capture=capture,
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
