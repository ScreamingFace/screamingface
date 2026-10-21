"""The hosted Engine as a community-cache page source (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).

Pinned here: one streamed `GET /v1/cache/entries` per page with the filter's `model` values, the
cursor and `count=true` only when asked; gzip accepted and decoded; the request marked replay-safe
so the Access sign-in may resend it; 502/503/504 and transport failures are transient; 401/403
are authentication errors; 404 means the Engine does not serve the community cache; any other
refusal carries the Engine's own problem detail.
"""

from __future__ import annotations

import gzip
import json

import httpx
import pytest

from screamingface._cache.pages import PAGE_SCHEMA, MalformedPage
from screamingface._cache.remote import HostedPages, TransientPageError
from screamingface._core.wire import _REPLAY_SAFE
from screamingface.errors import AuthenticationError, PlanningError

_PAGE = (
    json.dumps({"schema": PAGE_SCHEMA, "revisions": {"parameter_contract": "p1"}})
    + "\n"
    + json.dumps({"key_hash": "a" * 64})
    + "\n"
    + '{"next": null}\n'
).encode()


def _source(handler, models: tuple[str, ...] = ()) -> tuple[HostedPages, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.Client(base_url="https://engine.test/", transport=httpx.MockTransport(capture))
    return HostedPages(http, models), seen


_ZIPPED = gzip.compress(_PAGE)


class _Streamed(httpx.SyncByteStream):
    """A body delivered as a network stream (httpx reads a `content=` body eagerly)."""

    def __iter__(self):
        yield _ZIPPED[:40]
        yield _ZIPPED[40:]


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        stream=_Streamed(),
        headers={"content-type": "application/x-ndjson", "content-encoding": "gzip"},
    )


def test_a_page_request_carries_the_filter_cursor_and_count() -> None:
    source, seen = _source(_ok, models=("m1", "m2"))

    with source.open(after="cur", count=True) as (lines, _bytes):
        list(lines)

    [request] = seen
    assert request.method == "GET"
    assert request.url.path == "/v1/cache/entries"
    assert request.url.params.multi_items() == [
        ("model", "m1"),
        ("model", "m2"),
        ("after", "cur"),
        ("count", "true"),
    ]
    assert request.headers["accept-encoding"] == "gzip"
    assert request.extensions[_REPLAY_SAFE] is True


def test_a_first_page_without_a_cursor_or_count_asks_for_neither() -> None:
    source, seen = _source(_ok)

    with source.open(after=None, count=False) as (lines, _bytes):
        list(lines)

    assert seen[0].url.params.multi_items() == []


def test_a_gzip_page_is_read_as_lines_and_its_bytes_are_counted() -> None:
    source, _ = _source(_ok)

    with source.open(after=None, count=False) as (lines, received):
        read = list(lines)

    assert read == _PAGE.decode().splitlines()
    assert received() == len(_ZIPPED)
    assert source.origin == "https://engine.test"


@pytest.mark.parametrize("status", [502, 503, 504])
def test_an_edge_or_gateway_hiccup_is_transient(status: int) -> None:
    source, _ = _source(lambda _r: httpx.Response(status))

    with pytest.raises(TransientPageError), source.open(after=None, count=False):
        pass


def test_a_transport_failure_is_transient() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    source, _ = _source(refuse)

    with (
        pytest.raises(TransientPageError, match="ConnectError"),
        source.open(after=None, count=False),
    ):
        pass


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_identity_is_an_authentication_error(status: int) -> None:
    source, _ = _source(lambda _r: httpx.Response(status))

    with pytest.raises(AuthenticationError) as raised, source.open(after=None, count=False):
        pass

    assert raised.value.code == "authentication_required"


def test_an_engine_without_the_route_says_so() -> None:
    source, _ = _source(lambda _r: httpx.Response(404))

    with pytest.raises(PlanningError) as raised, source.open(after=None, count=False):
        pass

    assert raised.value.code == "community_cache_unsupported"


def test_any_other_refusal_carries_the_engines_problem_detail() -> None:
    problem = {
        "type": "about:blank",
        "title": "Unprocessable",
        "status": 422,
        "detail": "bad model",
    }
    source, _ = _source(
        lambda _r: httpx.Response(
            422, json=problem, headers={"content-type": "application/problem+json"}
        )
    )

    with pytest.raises(PlanningError) as raised, source.open(after=None, count=False):
        pass

    assert "bad model" in raised.value.message
    assert raised.value.status == 422


def test_a_corrupt_compressed_page_is_transient() -> None:
    class _Corrupt(httpx.SyncByteStream):
        def __iter__(self):
            yield b"not gzip at all"

    source, _ = _source(
        lambda _r: httpx.Response(200, stream=_Corrupt(), headers={"content-encoding": "gzip"})
    )

    with (
        pytest.raises(TransientPageError, match="DecodingError"),
        source.open(after=None, count=False) as (lines, _bytes),
    ):
        list(lines)


@pytest.mark.parametrize("status", [408, 429, 520, 524])
def test_the_sdks_shared_retryable_statuses_are_transient(status: int) -> None:
    source, _ = _source(lambda _r: httpx.Response(status))

    with pytest.raises(TransientPageError) as raised, source.open(after=None, count=False):
        pass

    assert raised.value.retry_after is None


def test_a_rate_limited_page_carries_the_engines_retry_after() -> None:
    source, _ = _source(lambda _r: httpx.Response(429, headers={"retry-after": "7"}))

    with pytest.raises(TransientPageError) as raised, source.open(after=None, count=False):
        pass

    assert raised.value.retry_after == 7.0


# --- PR #1446 review round 3: bounded lines and refusal bodies -----------------------------------


class _Chunks(httpx.SyncByteStream):
    """An identity-encoded body in the given chunks, counting how many were read."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.read = 0

    def __iter__(self):
        for chunk in self._chunks:
            self.read += 1
            yield chunk


def _serving(stream: httpx.SyncByteStream, status: int = 200, **headers: str) -> HostedPages:
    source, _ = _source(lambda _r: httpx.Response(status, stream=stream, headers=headers))
    return source


def test_lines_are_split_on_bytes_so_a_character_cut_between_chunks_survives() -> None:
    row = json.dumps({"key_hash": "a", "response_json": "été"}, ensure_ascii=False)
    body = f"{row}\n{row}\n".encode()
    cut = body.index("é".encode()) + 1  # inside the two-byte é

    with _serving(_Chunks([body[:cut], body[cut:]])).open(after=None, count=False) as (lines, _b):
        assert list(lines) == [row, row]


def test_a_line_over_the_cap_is_malformed_before_it_is_decoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY: one newline-free line (or a gzip bomb) would otherwise be buffered whole.
    monkeypatch.setattr("screamingface._cache.remote._MAX_LINE_BYTES", 8)
    source = _serving(_Chunks([b"12345678\n", b"12345", b"6789"]))

    with source.open(after=None, count=False) as (lines, _bytes):
        assert next(lines) == "12345678"  # exactly at the cap is a line
        with pytest.raises(MalformedPage, match="longer than"):
            next(lines)


def test_a_line_that_is_not_utf8_is_malformed() -> None:
    source = _serving(_Chunks([b"\xff\xfe\n"]))

    with (
        pytest.raises(MalformedPage, match="UTF-8"),
        source.open(after=None, count=False) as (lines, _bytes),
    ):
        list(lines)


def test_a_retryable_status_is_classified_without_reading_its_body() -> None:
    class _Unreadable(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("the body of a retryable status was read")
            yield b""  # pragma: no cover

    with (
        pytest.raises(TransientPageError),
        _serving(_Unreadable(), 503).open(after=None, count=False),
    ):
        pass


def test_a_refusal_reads_only_a_bounded_prefix_of_its_body() -> None:
    chunk = b"x" * 65_536
    stream = _Chunks([chunk] * 10)

    with (
        pytest.raises(PlanningError),
        _serving(stream, 422).open(after=None, count=False),
    ):
        pass

    assert stream.read == 1
