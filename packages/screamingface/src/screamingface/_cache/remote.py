"""The hosted Engine as a source of community-cache pages (epic OME-1311).

One streamed `GET /v1/cache/entries` per page, through a `Client`'s own engine session, so the
caller's Cloudflare Access sign-in is the one every other SDK call uses (spec decision 14). The
body is decoded by httpx as it arrives and handed on line by line.

WHY the replay-safe extension: a page request is a GET with no side effects, so the Access flow
may send it again after a browser sign-in (`_core/wire.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from screamingface._core.retry import _RETRYABLE_STATUS, _retry_after_seconds
from screamingface._core.wire import _REPLAY_SAFE
from screamingface.errors import AuthenticationError, PlanningError

if TYPE_CHECKING:
    import httpx

_ENTRIES_PATH: Final = "/v1/cache/entries"


class TransientPageError(Exception):
    """This page could not be read just now; asking for it again may succeed."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class HostedPages:
    """Pages of one pull's filter, read from one hosted Engine session."""

    def __init__(self, http: httpx.Client, models: Sequence[str]) -> None:
        self._http = http
        self._models = tuple(models)

    @property
    def origin(self) -> str:
        return str(self._http.base_url).rstrip("/")

    @contextmanager
    def open(
        self, *, after: str | None, count: bool
    ) -> Iterator[tuple[Iterator[str], Callable[[], int]]]:
        """The page's lines, and a reading of the compressed bytes received so far."""
        import httpx

        params: dict[str, str | list[str]] = {}
        if self._models:
            params["model"] = list(self._models)
        if after is not None:
            params["after"] = after
        if count:
            params["count"] = "true"
        try:
            with self._http.stream(
                "GET",
                _ENTRIES_PATH,
                params=params,
                headers={"Accept-Encoding": "gzip"},
                extensions={_REPLAY_SAFE: True},
            ) as response:
                if response.status_code != 200:
                    response.read()
                    _raise_for(response)
                yield response.iter_lines(), lambda: response.num_bytes_downloaded
        # WHY DecodingError: a gzip stream cut or garbled in transit reads as corrupt, not dropped.
        except (httpx.TransportError, httpx.DecodingError) as exc:
            raise TransientPageError(
                f"the Engine could not be reached ({type(exc).__name__})"
            ) from exc


def _raise_for(response: httpx.Response) -> None:
    from screamingface._engine.transport import _problem_parts

    status = response.status_code
    # WHY the SDK's shared set: a page crosses the same Cloudflare edge as every other call, and
    # the Engine's own cache route answers 429 + Retry-After when reads are rate limited. Every
    # other status is a fact about the request, not about the moment.
    if status in _RETRYABLE_STATUS:
        raise TransientPageError(
            f"the Engine answered {status}", retry_after=_retry_after_seconds(response)
        )
    detail, code, details = _problem_parts(response)
    if status in {401, 403}:
        raise AuthenticationError(
            f"The Engine refused the community-cache request: {detail}",
            code="authentication_required",
            status=status,
            permanent=True,
            details=details,
        )
    if status == 404:
        raise PlanningError(
            "This Engine does not serve the community cache",
            code="community_cache_unsupported",
            status=status,
            permanent=True,
            details=details,
        )
    raise PlanningError(
        f"The Engine refused the community-cache request: {detail}",
        code=code or "community_cache_request_refused",
        status=status,
        permanent=True,
        details=details,
    )


__all__ = ["HostedPages", "TransientPageError"]
