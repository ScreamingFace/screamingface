"""GitHub releases through a GitHub App (C7): the `ReleasePublisher` adapter and its token source.

Mirrors `apps/aigateway/src/aigateway/core/object_store.py` by shape: one client, sanitized
errors. FEATURE: OME-1307 (E14).

INVARIANT: the App private key, the App JWT and the installation token are key material. They
never reach a log line, an exception message or `last_error`. An error message holds the status
code and GitHub's own `message` field only, cut to 200 chars (`_raise_for`).
INVARIANT (PB-D7): one installation token per job; nothing is cached between jobs.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import httpx
import jwt

from scoreboard.core.publish.ports import AssetRef, PublisherError, ReleaseRef

_API_VERSION = "2022-11-28"
_JSON_ACCEPT = "application/vnd.github+json"
_API_TIMEOUT_S = 30.0
_TRANSFER_TIMEOUT_S = 120.0
_MESSAGE_MAX = 200
_UPLOAD_TEMPLATE = re.compile(r"\{\?[^}]*\}$")


def _message_of(response: httpx.Response) -> str:
    """GitHub's `message` field, or "" when the body is not the usual JSON error."""
    try:
        body = response.json()
    except ValueError:
        return ""
    message = body.get("message") if isinstance(body, dict) else None
    return message if isinstance(message, str) else ""


def _retry_after_s(response: httpx.Response) -> float | None:
    """`Retry-After` seconds, else the rate-limit reset time minus now, else None."""
    header = response.headers.get("Retry-After")
    if header is not None and header.isdigit():
        return float(header)
    reset = response.headers.get("x-ratelimit-reset")
    if reset is not None and reset.isdigit():
        return max(0.0, float(reset) - time.time())
    return None


def _is_retryable(response: httpx.Response, message: str) -> bool:
    status = response.status_code
    if status >= 500 or status == 429:
        return True
    return status == 403 and (
        response.headers.get("x-ratelimit-remaining") == "0"
        or "secondary rate limit" in message.lower()
    )


def _raise_for(response: httpx.Response) -> None:
    """Map a non-2xx response to a sanitized `PublisherError`, or return for a 2xx."""
    if response.is_success:
        return
    message = _message_of(response)
    text = f"HTTP {response.status_code}: {message}" if message else f"HTTP {response.status_code}"
    retryable = _is_retryable(response, message)
    raise PublisherError(
        text[:_MESSAGE_MAX],
        retryable=retryable,
        retry_after_s=_retry_after_s(response) if retryable else None,
    )


def _release_of(body: dict[str, Any]) -> ReleaseRef:
    return ReleaseRef(
        id=int(body["id"]),
        tag=str(body["tag_name"]),
        html_url=str(body["html_url"]),
        # WHY strip: GitHub sends a URI template ("...assets{?name,label}").
        upload_url=_UPLOAD_TEMPLATE.sub("", str(body["upload_url"])),
        assets=tuple(AssetRef(int(a["id"]), str(a["name"])) for a in body.get("assets", [])),
    )


class TokenSource(Protocol):
    async def token(self) -> str: ...


class GitHubAppTokenSource:
    """Mints a GitHub App installation token: an RS256 App JWT, exchanged for the token."""

    def __init__(
        self,
        app_id: str,
        installation_id: str,
        private_key_pem: str,
        api_url: str,
        clock: Callable[[], datetime],
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._app_id = app_id
        self._installation_id = installation_id
        self._private_key = private_key_pem
        self._api_url = api_url.rstrip("/")
        self._clock = clock
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=_API_TIMEOUT_S))

    async def token(self) -> str:
        now = int(self._clock().timestamp())
        app_jwt = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self._app_id},
            self._private_key,
            algorithm="RS256",
        )
        url = f"{self._api_url}/app/installations/{self._installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": _JSON_ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
        }
        try:
            async with self._client_factory() as client:
                response = await client.post(url, headers=headers)
        except httpx.HTTPError as exc:
            raise PublisherError(
                f"token request failed ({type(exc).__name__})", retryable=True
            ) from exc
        _raise_for(response)
        return str(response.json()["token"])


class GitHubReleasePublisher:
    """The `ReleasePublisher` port over the GitHub REST API, for one repo and one token."""

    def __init__(self, client: httpx.AsyncClient, token: str, repo: str, api_url: str) -> None:
        self._client = client
        self._token = token
        self._repo = repo
        self._api_url = api_url.rstrip("/")

    def _headers(self, **extra: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": _JSON_ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
            **extra,
        }

    async def _send(
        self, method: str, url: str, *, timeout: float, headers: dict[str, str], **options: Any
    ) -> httpx.Response:
        try:
            return await self._client.request(
                method, url, headers=headers, timeout=timeout, **options
            )
        except httpx.HTTPError as exc:
            # WHY the class name only: the text of a transport error can carry the URL.
            raise PublisherError(
                f"{method} request failed ({type(exc).__name__})", retryable=True
            ) from exc

    def _repo_url(self, path: str) -> str:
        return f"{self._api_url}/repos/{self._repo}/{path}"

    async def get_release_by_tag(self, tag: str) -> ReleaseRef | None:
        response = await self._send(
            "GET",
            self._repo_url(f"releases/tags/{tag}"),
            timeout=_API_TIMEOUT_S,
            headers=self._headers(),
        )
        if response.status_code == 404:
            return None
        _raise_for(response)
        return _release_of(response.json())

    async def create_release(self, tag: str, name: str, body: str) -> ReleaseRef:
        response = await self._send(
            "POST",
            self._repo_url("releases"),
            timeout=_API_TIMEOUT_S,
            headers=self._headers(),
            json={"tag_name": tag, "name": name, "body": body, "draft": False},
        )
        _raise_for(response)
        return _release_of(response.json())

    async def upload_asset(
        self, release: ReleaseRef, name: str, data: bytes, content_type: str
    ) -> AssetRef:
        response = await self._send(
            "POST",
            release.upload_url,
            timeout=_TRANSFER_TIMEOUT_S,
            headers=self._headers(**{"Content-Type": content_type}),
            params={"name": name},
            content=data,
        )
        _raise_for(response)
        body = response.json()
        return AssetRef(int(body["id"]), str(body["name"]))

    async def download_asset(self, asset: AssetRef) -> bytes:
        # WHY follow redirects: GitHub answers with a redirect to the object store. httpx drops the
        # Authorization header when a redirect leaves the origin, so the token does not follow.
        response = await self._send(
            "GET",
            self._repo_url(f"releases/assets/{asset.id}"),
            timeout=_TRANSFER_TIMEOUT_S,
            headers=self._headers(Accept="application/octet-stream"),
            follow_redirects=True,
        )
        _raise_for(response)
        return response.content

    async def delete_release(self, release_id: int) -> None:
        """204 and 404 both mean the release is gone."""
        response = await self._send(
            "DELETE",
            self._repo_url(f"releases/{release_id}"),
            timeout=_API_TIMEOUT_S,
            headers=self._headers(),
        )
        if response.status_code != 404:
            _raise_for(response)

    async def delete_tag(self, tag: str) -> None:
        """204, 404 and 422 all mean the tag is gone (or never was)."""
        response = await self._send(
            "DELETE",
            self._repo_url(f"git/refs/tags/{tag}"),
            timeout=_API_TIMEOUT_S,
            headers=self._headers(),
        )
        if response.status_code not in (404, 422):
            _raise_for(response)


class GitHubReleasePublisherFactory:
    """The `ReleasePublisherFactory` port: one publisher per job, each with a fresh token (PB-D7).

    WHY it owns the client: one pooled client serves every job, and `aclose` ends it at shutdown.
    The client lives here so that only `adapters/` imports `httpx` (the layering guard, PB-20a).
    """

    def __init__(self, source: TokenSource, repo: str, api_url: str) -> None:
        self._source = source
        self._repo = repo
        self._api_url = api_url
        self._client = httpx.AsyncClient()

    async def __call__(self) -> GitHubReleasePublisher:
        token = await self._source.token()
        return GitHubReleasePublisher(self._client, token, self._repo, self._api_url)

    async def aclose(self) -> None:
        await self._client.aclose()
