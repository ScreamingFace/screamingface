"""The OpenAI client options of sf.Client and sf.AsyncClient (contracts C1.7, D19 to D22)."""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

import httpx

from screamingface._client_connections import _http_origin
from screamingface._inference.request import check_retries, timeout_seconds
from screamingface.warnings import IgnoredParameterWarning

# WHY: the OpenAI client options that the SDK does not use (C1.7, D22). They are accepted, so that
# the line that makes the client can change with no other change. Each one gives one warning.
IGNORED_CLIENT_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "organization",
        "project",
        "webhook_secret",
        "websocket_base_url",
        "default_headers",
        "default_query",
        "http_client",
        "admin_api_key",
        "workload_identity",
        "provider",
    }
)


@dataclass(frozen=True, slots=True)
class ClientOptions:
    """The values that one SF client keeps from its OpenAI client options (C1.7)."""

    engine_url: str  # the checked Engine origin
    chat_timeout: float | None
    chat_max_retries: int


def client_options(
    owner: str,
    *,
    engine_url: Any,
    base_url: object,
    api_key: object,
    timeout: object,
    max_retries: object,
    other: Mapping[str, Any],
    stacklevel: int = 3,
) -> ClientOptions:
    """Check the OpenAI client options of one SF client and give its values (C1.7).

    The order is fixed: each error comes before each warning, so a call that raises gives no
    warning. The caller checks its other arguments before this call for the same reason.
    AIDEV-NOTE: stacklevel 3 names the caller of the __init__ that calls this function.
    """

    for name in other:
        if name not in IGNORED_CLIENT_OPTIONS:
            raise TypeError(f"{owner}.__init__() got an unexpected keyword argument {name!r}")
    origin = _origin(engine_url, base_url)
    chat_timeout = timeout_seconds(timeout)
    chat_max_retries = check_retries(max_retries)
    # INVARIANT (D19): the api_key value is never stored and never put in a warning text.
    if api_key is not None:
        text = (
            "ScreamingFace does not use the OpenAI client option 'api_key': the client does not "
            "keep it and does not send it. The client signs in to the SF Engine itself; store a "
            "provider key with sf.connect(...)."
        )
        warnings.warn(text, IgnoredParameterWarning, stacklevel=stacklevel)
    for name, value in other.items():
        if value is not None:
            text = (
                f"ScreamingFace does not use the OpenAI client option {name!r}: the client does "
                "not keep it and does not send it."
            )
            warnings.warn(text, IgnoredParameterWarning, stacklevel=stacklevel)
    return ClientOptions(
        engine_url=origin, chat_timeout=chat_timeout, chat_max_retries=chat_max_retries
    )


def _origin(engine_url: Any, base_url: object) -> str:
    """The checked Engine origin of a client, from engine_url or from base_url (C1.7, D20)."""

    # WHY here: screamingface.client imports this module inside its constructors.
    from screamingface.client import DEFAULT_ENGINE_URL  # noqa: PLC0415

    if base_url is None:
        return _http_origin(engine_url, "engine_url")
    if engine_url != DEFAULT_ENGINE_URL:
        raise TypeError("give one of engine_url and base_url, not both")
    return _engine_url_of(base_url)


def _engine_url_of(value: object) -> str:
    """The Engine origin of a base_url value, with or without the path /v1 (C1.7, D20)."""

    if isinstance(value, httpx.URL):
        value = str(value)
    if not isinstance(value, str):
        raise TypeError("base_url must be a URL string")
    try:
        parts = urlsplit(value.strip())
        # WHY the path only: a host with the name v1 is a valid Engine host.
        path = parts.path.rstrip("/")
        text = urlunsplit(parts._replace(path="" if path == "/v1" else path))
        # WHY the shared check: base_url and engine_url have one rule for an Engine origin.
        return _http_origin(text, "base_url")
    except ValueError:
        raise ValueError(
            "base_url must be a SF Engine URL: an HTTP(S) origin, with or without the path /v1"
        ) from None


__all__ = ["IGNORED_CLIENT_OPTIONS", "ClientOptions", "client_options"]
