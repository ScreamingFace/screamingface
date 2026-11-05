"""A signed source URL's userinfo, query and fragment never reach a source error's text.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1539``) — push security review.
STORY: as an operator I hand a run a pre-signed ``https://…?X-Amz-Signature=…`` source; when
the fetch fails (an optional source is then omitted and its error logged), the error names the
source by scheme, host and path — never by its signature or credentials.

INVARIANT: every error the base IO layers (``io/http.py``, ``io/media.py``, ``io/static.py``)
build from a source URL shows it through :func:`url4.core.url_display.display_url`: the message,
its repr, its notes and every chained cause / context. Codes and ``permanent`` are unchanged.
No network: injected ``httpx.MockTransport`` clients, or the guarded transport's inner mock.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
import url4.io.http as http_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.core.url_display import UNPARSEABLE, display_url
from url4.io.http import HttpIOLayer, SourceGuard
from url4.io.layer import FetchRequest
from url4.io.media import bare_media_type, require_text
from url4.io.static import StaticIOLayer

SECRETS = ("USERSECRET", "PASSSECRET", "SIGSECRET", "TOKSECRET", "FRAGSECRET", "LOCSECRET")
HOST = "files.example"
PATH = "/bucket/photo.png"
PLAIN = f"https://{HOST}{PATH}"
QUERY = "?X-Amz-Signature=SIGSECRET&token=TOKSECRET#FRAGSECRET"
SIGNED = f"https://USERSECRET:PASSSECRET@{HOST}{PATH}{QUERY}"  # userinfo + query + fragment
UNCREDENTIALED = PLAIN + QUERY  # what the owned (guarded) client may fetch
LOCATION = "https://cdn.example/next.png?sig=LOCSECRET"
PUBLIC = "93.184.216.34"

Handler = Callable[[httpx.Request], httpx.Response]


def _chain(error: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    pending: list[BaseException | None] = [error]
    while pending:
        current = pending.pop()
        if current is None or any(current is known for known in seen):
            continue
        seen.append(current)
        pending += [current.__cause__, current.__context__]
    return seen


def _assert_redacted(error: BaseException) -> None:
    """No secret anywhere a log could print; host and path still name the source."""
    for link in _chain(error):
        for text in (str(link), repr(link), *getattr(link, "__notes__", [])):
            leaked = [secret for secret in SECRETS if secret in text]
            assert leaked == [], f"{type(link).__name__} leaks {leaked}: {text!r}"
    assert f"{HOST}{PATH}" in str(error)


def _client(
    handler: Handler, *, follow_redirects: bool = False, max_redirects: int = 20
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
    )


async def _failed_fetch(
    handler: Handler, url: str = SIGNED, *, follow_redirects: bool = False, max_redirects: int = 20
) -> ResolutionError:
    async with _client(
        handler, follow_redirects=follow_redirects, max_redirects=max_redirects
    ) as client:
        io = HttpIOLayer(client=client)
        with pytest.raises(ResolutionError) as caught:
            await io.fetch(url, relative=False)
    return caught.value


# -- the helper ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        (SIGNED, f"https://***@{HOST}{PATH}?<redacted>#<redacted>"),
        (PLAIN, PLAIN),
        # WHY: urlsplit, like WHATWG, drops a tab and strips leading spaces — the secret too.
        (
            f" https://u:PASSSECRET@{HOST}{PATH}?sig=SIG\tSECRET",
            f"https://***@{HOST}{PATH}?<redacted>",
        ),
        ("https://u:PASSSECRET@[::1/x?sig=SIGSECRET", UNPARSEABLE),
    ],
)
def test_display_url_hides_what_a_source_error_must_not_show(raw: str, shown: str) -> None:
    assert display_url(raw) == shown


# -- io/http.py ----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "permanent"), [(404, True), (403, True), (503, False)])
async def test_a_status_error_hides_the_signed_url_in_message_and_cause(
    status: int, permanent: bool
) -> None:
    error = await _failed_fetch(lambda _request: httpx.Response(status))
    assert error.permanent is permanent
    assert isinstance(error.__cause__, httpx.HTTPStatusError)  # the cause type is unchanged
    assert error.__cause__.response.status_code == status
    assert f"'{status} " in str(error) and f"'{status} " in str(error.__cause__)
    _assert_redacted(error)


@pytest.mark.asyncio
async def test_a_typed_404_on_the_bytes_path_keeps_its_code_and_hides_the_url() -> None:
    async with _client(lambda _request: httpx.Response(404)) as client:
        io = HttpIOLayer(client=client)
        with pytest.raises(ResolutionError) as caught:
            await io.fetch_bytes(FetchRequest(target=SIGNED, relative=False))
    assert caught.value.code == ErrorCode.SOURCE_NOT_FOUND
    _assert_redacted(caught.value)


@pytest.mark.asyncio
async def test_a_redirect_status_hides_its_location_query() -> None:
    def redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": LOCATION})

    error = await _failed_fetch(redirect, follow_redirects=False)
    assert "cdn.example/next.png?<redacted>" in str(error.__cause__)
    _assert_redacted(error)


@pytest.mark.asyncio
async def test_a_connect_error_hides_the_signed_url() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    error = await _failed_fetch(refuse)
    assert isinstance(error.__cause__, httpx.ConnectError)
    _assert_redacted(error)


@pytest.mark.asyncio
async def test_a_connect_timeout_keeps_its_code_and_hides_the_url() -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    error = await _failed_fetch(hang)
    assert error.code == ErrorCode.SOURCE_TIMEOUT
    _assert_redacted(error)


@pytest.mark.asyncio
async def test_the_redirect_limit_hides_the_signed_url() -> None:
    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url)})

    error = await _failed_fetch(loop, follow_redirects=True, max_redirects=2)
    assert error.code == ErrorCode.SOURCE_REDIRECT_LIMIT
    assert error.permanent is True
    _assert_redacted(error)


class _Net:
    async def resolve(self, host: str, port: int) -> Sequence[str]:
        return [PUBLIC]


@pytest.mark.asyncio
async def test_the_total_deadline_hides_the_signed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        guarded_mod,
        "_inner_transport",
        lambda: httpx.MockTransport(lambda _r: httpx.Response(200, text="late")),
    )
    monkeypatch.setattr(http_mod, "past", lambda _deadline: True)  # answered after the deadline
    async with HttpIOLayer(guard=SourceGuard(), resolver=_Net().resolve) as io:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch(UNCREDENTIALED, relative=False)
    assert caught.value.code == ErrorCode.SOURCE_TIMEOUT
    assert "total deadline" in str(caught.value)
    _assert_redacted(caught.value)


@pytest.mark.asyncio
async def test_a_malformed_credentialed_url_hides_its_query_too() -> None:
    def unreachable(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("a malformed target must not reach the transport")

    url = f"https://USERSECRET:PASSSECRET@{HOST}:port{PATH}{QUERY}"
    async with _client(unreachable) as client:
        with pytest.raises(ResolutionError) as caught:
            await HttpIOLayer(client=client).fetch(url, relative=False)
    assert caught.value.__cause__ is None  # nothing chained, as before
    for link in _chain(caught.value):
        assert [s for s in SECRETS if s in str(link) + repr(link)] == []


# -- io/media.py ---------------------------------------------------------------------------


def test_require_text_hides_the_signed_target() -> None:
    with pytest.raises(ResolutionError) as caught:
        require_text(SIGNED, "image/png")
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert caught.value.permanent is True
    assert "'image/png'" in str(caught.value)
    _assert_redacted(caught.value)


def test_bare_media_type_hides_the_signed_target() -> None:
    with pytest.raises(ResolutionError) as caught:
        bare_media_type(SIGNED, "image/png, text/html")
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    _assert_redacted(caught.value)


@pytest.mark.asyncio
async def test_a_binary_source_on_the_http_text_path_hides_the_signed_url() -> None:
    error = await _failed_fetch(
        lambda _request: httpx.Response(
            200, content=b"\x89PNG", headers={"content-type": "image/png"}
        )
    )
    assert error.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    _assert_redacted(error)


# -- io/static.py --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_missing_static_mapping_hides_the_signed_target() -> None:
    with pytest.raises(ResolutionError) as caught:
        await StaticIOLayer().fetch(SIGNED, relative=False)
    assert "no fetch mapping" in str(caught.value)
    _assert_redacted(caught.value)


@pytest.mark.asyncio
async def test_a_missing_static_bytes_source_hides_userinfo_and_fragment() -> None:
    target = f"https://USERSECRET:PASSSECRET@{HOST}{PATH}#FRAGSECRET"  # no '?': the C5 branch
    with pytest.raises(ResolutionError) as caught:
        await StaticIOLayer().fetch_bytes(FetchRequest(target=target, relative=False))
    assert caught.value.code == ErrorCode.SOURCE_NOT_FOUND
    _assert_redacted(caught.value)
