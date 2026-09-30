"""PB-14a, PB-20 — the GitHub release adapter (C7), against fixture bodies.

FEATURE: OME-1307 (E14). The bodies in `tests/fixtures/github/` are hand-written from the shapes
of the GitHub REST documentation (release: `id`, `tag_name`, `html_url`, `upload_url`,
`assets[{id, name}]`). They are NOT recorded from a live call; the nightly PB-22 checks the live
API.

INVARIANTS under test: an error message carries the status code and GitHub's `message` only (never
a header or a token), a retryable failure is told from a final one, and a 404 on a delete counts
as done.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scoreboard.adapters.github_releases import (
    GitHubAppTokenSource,
    GitHubReleasePublisher,
    GitHubReleasePublisherFactory,
)
from scoreboard.core.publish.ports import AssetRef, PublisherError, ReleaseRef

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "github"
_REPO = "ScreamingFace/screamingface-cache-versions"
_API = "https://api.github.com"
_TAG = "cv-6f1c1d0a-0000-4000-8000-000000000001"
_TOKEN = "ghs_secrettokenvalue"


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


# WHY read, not spelled out: the download body is opaque bytes, and the test proves they arrive
# unchanged (a pre-commit hook may add a final newline to the fixture file).
_DOWNLOAD = _fixture("asset_download_200.bin")


def _publisher(handler: httpx.MockTransport) -> GitHubReleasePublisher:
    return GitHubReleasePublisher(httpx.AsyncClient(transport=handler), _TOKEN, _REPO, _API)


def _json(name: str, status: int) -> httpx.Response:
    return httpx.Response(
        status, content=_fixture(name), headers={"content-type": "application/json"}
    )


class _ContractStub:
    """Answers the calls of the contract test from the fixture bodies and records each request."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        self._tag_lookups = iter([404, 200])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        for method, pattern, answer in self._routes():
            if request.method == method and re.search(pattern, request.url.path):
                return answer()
        raise AssertionError(f"unexpected call {request.method} {request.url}")

    def _routes(self) -> list[tuple[str, str, Callable[[], httpx.Response]]]:
        return [
            ("GET", r"/releases/tags/", self._lookup),
            ("POST", r"/releases$", lambda: _json("release_create_201.json", 201)),
            ("POST", r"/assets$", lambda: _json("asset_upload_201.json", 201)),
            ("GET", r"/releases/assets/", lambda: httpx.Response(200, content=_DOWNLOAD)),
            # A tag that is already gone counts as done.
            ("DELETE", r"/git/refs/tags/", lambda: httpx.Response(404)),
            ("DELETE", r"/releases/\d+$", lambda: httpx.Response(204)),
        ]

    def _lookup(self) -> httpx.Response:
        status = next(self._tag_lookups)
        return _json(
            "release_get_404.json" if status == 404 else "release_get_by_tag_200.json", status
        )


async def _exercise() -> tuple[_ContractStub, dict[str, Any]]:
    stub = _ContractStub()
    publisher = _publisher(httpx.MockTransport(stub))
    results: dict[str, Any] = {"missing": await publisher.get_release_by_tag(_TAG)}
    results["found"] = await publisher.get_release_by_tag(_TAG)
    results["created"] = await publisher.create_release(_TAG, f"Cache version {_TAG}", "body text")
    results["uploaded"] = await publisher.upload_asset(
        results["created"], "manifest.json", b"{}", "application/json"
    )
    results["downloaded"] = await publisher.download_asset(AssetRef(9001, "entries.jsonl.gz"))
    await publisher.delete_release(4242)
    await publisher.delete_tag(_TAG)
    return stub, results


async def test_github_adapter_contract_results() -> None:
    _, results = await _exercise()

    assert results["missing"] is None
    assert results["found"] == ReleaseRef(
        id=4242,
        tag=_TAG,
        html_url=f"https://github.com/{_REPO}/releases/tag/{_TAG}",
        upload_url=f"https://uploads.github.com/repos/{_REPO}/releases/4242/assets",
        assets=(AssetRef(9001, "entries.jsonl.gz"), AssetRef(9002, "manifest.json")),
    )
    # The `{?name,label}` template of the upload URL is removed.
    assert results["created"].upload_url == results["found"].upload_url
    assert results["uploaded"] == AssetRef(id=9002, name="manifest.json")
    assert results["downloaded"] == _DOWNLOAD


async def test_github_adapter_contract_requests() -> None:
    stub, _ = await _exercise()

    lookup, _again, create, upload, download, delete_release, delete_tag = stub.seen
    assert (lookup.method, lookup.url.path) == ("GET", f"/repos/{_REPO}/releases/tags/{_TAG}")
    assert (create.method, create.url.path) == ("POST", f"/repos/{_REPO}/releases")
    assert json.loads(create.read()) == {
        "tag_name": _TAG,
        "name": f"Cache version {_TAG}",
        "body": "body text",
        "draft": False,
    }
    assert str(upload.url) == (
        f"https://uploads.github.com/repos/{_REPO}/releases/4242/assets?name=manifest.json"
    )
    assert upload.headers["Content-Type"] == "application/json"
    assert upload.read() == b"{}"
    assert download.url.path == f"/repos/{_REPO}/releases/assets/9001"
    assert download.headers["Accept"] == "application/octet-stream"
    assert (delete_release.method, delete_release.url.path) == (
        "DELETE",
        f"/repos/{_REPO}/releases/4242",
    )
    assert (delete_tag.method, delete_tag.url.path) == (
        "DELETE",
        f"/repos/{_REPO}/git/refs/tags/{_TAG}",
    )
    for request in stub.seen:
        assert request.headers["Authorization"] == f"Bearer {_TOKEN}"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        if request is not download:
            assert request.headers["Accept"] == "application/vnd.github+json"


@pytest.mark.parametrize("status", [404, 422, 204])
async def test_delete_of_a_missing_tag_or_release_counts_as_done(status: int) -> None:
    publisher = _publisher(httpx.MockTransport(lambda request: httpx.Response(status)))

    await publisher.delete_tag(_TAG)
    if status != 422:
        await publisher.delete_release(4242)


async def test_a_delete_refused_with_another_status_is_an_error() -> None:
    publisher = _publisher(
        httpx.MockTransport(lambda request: httpx.Response(403, json={"message": "Forbidden"}))
    )

    with pytest.raises(PublisherError) as refused:
        await publisher.delete_release(4242)

    assert refused.value.retryable is False


async def _error_of(response: httpx.Response | Exception) -> PublisherError:
    def serve(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    publisher = _publisher(httpx.MockTransport(serve))
    with pytest.raises(PublisherError) as raised:
        await publisher.create_release(_TAG, "n", "b")
    return raised.value


async def test_error_mapping_retryable_and_retry_after() -> None:
    reset = str(int(time.time()) + 300)
    server = await _error_of(httpx.Response(500, json={"message": "Server Error"}))
    limited = await _error_of(
        httpx.Response(429, json={"message": "slow down"}, headers={"Retry-After": "120"})
    )
    exhausted = await _error_of(
        httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset},
        )
    )
    secondary = await _error_of(
        httpx.Response(403, json={"message": "You have exceeded a secondary rate limit."})
    )
    plain_403 = await _error_of(httpx.Response(403, json={"message": "Resource not accessible"}))
    invalid = await _error_of(httpx.Response(422, json={"message": "Validation Failed"}))
    timeout = await _error_of(httpx.ConnectTimeout("timed out"))

    assert (server.retryable, server.retry_after_s) == (True, None)
    assert (limited.retryable, limited.retry_after_s) == (True, 120.0)
    assert exhausted.retryable is True
    assert exhausted.retry_after_s == pytest.approx(300, abs=5)
    assert (secondary.retryable, secondary.retry_after_s) == (True, None)
    assert plain_403.retryable is False
    assert invalid.retryable is False
    assert timeout.retryable is True


async def test_an_error_message_carries_only_the_status_and_github_message() -> None:
    error = await _error_of(
        httpx.Response(
            401,
            json={"message": "Bad credentials " + "x" * 400},
            headers={"x-github-request-id": "SECRET-HEADER", "Authorization": _TOKEN},
        )
    )

    assert error.message.startswith("HTTP 401: Bad credentials")
    assert len(error.message) <= 200
    assert "SECRET-HEADER" not in error.message
    assert _TOKEN not in error.message
    assert "api.github.com" not in error.message
    assert "ConnectTimeout" in (await _error_of(httpx.ConnectTimeout("t"))).message


async def test_an_error_body_that_is_not_json_still_maps_to_the_status() -> None:
    error = await _error_of(httpx.Response(502, text="<html>Bad gateway</html>"))

    assert error.message == "HTTP 502"
    assert error.retryable is True


def _rsa_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


async def test_the_app_token_source_signs_an_rs256_jwt_and_returns_the_token() -> None:
    private_pem, public_pem = _rsa_pair()
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"token": _TOKEN, "expires_at": "2026-09-29T13:00:00Z"})

    source = GitHubAppTokenSource(
        "12345",
        "678",
        private_pem,
        _API,
        lambda: now,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(serve)),
    )

    assert await source.token() == _TOKEN
    assert await source.token() == _TOKEN

    # One token per job (PB-D7): no cache between two calls.
    assert len(seen) == 2
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", "/app/installations/678/access_tokens")
    bearer = request.headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        bearer, public_pem, algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False}
    )
    assert claims == {
        "iss": "12345",
        "iat": int(now.timestamp()) - 60,
        "exp": int(now.timestamp()) + 540,
    }
    assert jwt.get_unverified_header(bearer)["alg"] == "RS256"


async def test_the_app_token_source_error_does_not_leak_the_key_or_the_jwt() -> None:
    private_pem, _ = _rsa_pair()
    source = GitHubAppTokenSource(
        "12345",
        "678",
        private_pem,
        _API,
        lambda: datetime(2026, 9, 29, tzinfo=UTC),
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"message": "Bad credentials"})
            )
        ),
    )

    with pytest.raises(PublisherError) as refused:
        await source.token()

    assert refused.value.message == "HTTP 401: Bad credentials"
    assert refused.value.retryable is False
    assert "PRIVATE KEY" not in refused.value.message


class _CountingSource:
    def __init__(self) -> None:
        self.minted = 0

    async def token(self) -> str:
        self.minted += 1
        return f"token-{self.minted}"


async def test_the_publisher_factory_mints_one_token_per_job_and_closes_its_client() -> None:
    source = _CountingSource()
    factory = GitHubReleasePublisherFactory(source, _REPO, _API)

    first = await factory()
    second = await factory()

    # PB-D7: a fresh installation token for every job, never cached.
    assert source.minted == 2
    assert isinstance(first, GitHubReleasePublisher)
    assert first is not second
    await factory.aclose()


async def test_the_app_token_source_maps_a_transport_error_to_a_retryable_error() -> None:
    private_pem, _ = _rsa_pair()

    def serve(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    source = GitHubAppTokenSource(
        "12345",
        "678",
        private_pem,
        _API,
        lambda: datetime(2026, 9, 29, tzinfo=UTC),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(serve)),
    )

    with pytest.raises(PublisherError) as failed:
        await source.token()

    assert failed.value.retryable is True
    assert "ConnectTimeout" in failed.value.message
