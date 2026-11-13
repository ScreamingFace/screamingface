"""A signed attachment URL's query and fragment never reach a log line, a span or an error text.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``) — push security review.
STORY: as an operator I hand a run a pre-signed ``https://…/a.png?X-Amz-Signature=…`` source;
the run log, its spans and every error it raises name the source by scheme, host and path, and
the signature never lands in a log store.

INVARIANT: every message the attachment path builds from a source URL goes through
:func:`url4.core.url_display.display_url` — query and fragment replaced by fixed markers,
userinfo by ``***`` — and the helper never raises, whatever text it is handed.
"""

from __future__ import annotations

import logging

import pytest

from url4.core.errors import ErrorCode, ParseError, ResolutionError
from url4.core.url_display import UNPARSEABLE, display_url
from url4.dag import _materialize, compile_expression, run
from url4.io.static import StaticIOLayer
from url4.observe import Log
from url4.peer._bytes import no_bytes_port

SECRETS = ("SIGSECRET", "CREDSECRET", "TOKSECRET", "FRAGSECRET")
QUERY = "?X-Amz-Signature=SIGSECRET&X-Amz-Credential=CREDSECRET&token=TOKSECRET#FRAGSECRET"
TXT = "https://txt.example/notes.txt"
IMG = "https://img.example/photo.png"
ROWS = "https://rows.example/rows.json"
SIGNED_TXT, SIGNED_IMG, SIGNED_ROWS = TXT + QUERY, IMG + QUERY, ROWS + QUERY
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-redaction"


def _leaks(text: str) -> list[str]:
    return [secret for secret in SECRETS if secret in text]


def _error_text(exc: BaseException) -> str:
    """The error's own text plus every chained cause/context — all of it may be logged."""
    parts: list[str] = []
    seen: BaseException | None = exc
    while seen is not None:
        parts.extend((str(seen), repr(seen)))
        seen = seen.__cause__ or seen.__context__
    return "\n".join(parts)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def on_event(self, event: object) -> None:
        self.events.append(event)


class _Model:
    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        return "ok"


def _web() -> StaticIOLayer:
    bodies: dict[str, str | bytes] = {SIGNED_TXT: "notes", SIGNED_IMG: PNG, SIGNED_ROWS: "[1]"}
    types = {SIGNED_TXT: "text/plain", SIGNED_IMG: "image/png", SIGNED_ROWS: "application/json"}
    return StaticIOLayer(bodies, media_types=types)


# -- the helper ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        (IMG, IMG),
        ("https://h.example:8443/a/b.png", "https://h.example:8443/a/b.png"),
        (SIGNED_IMG, IMG + "?<redacted>#<redacted>"),
        ("https://h.example/a.png?sig=S", "https://h.example/a.png?<redacted>"),
        ("https://h.example/a.png#frag", "https://h.example/a.png#<redacted>"),
        ("https://h.example?token=T", "https://h.example?<redacted>"),
        ("https://user:pw@h.example/a?sig=S", "https://***@h.example/a?<redacted>"),
        ("/files/$name?sig=S", "/files/$name?<redacted>"),
        ("$item.url", "$item.url"),
        ("", ""),
    ],
)
def test_display_url_keeps_scheme_host_port_and_path_only(raw: str, shown: str) -> None:
    assert display_url(raw) == shown


@pytest.mark.parametrize(
    "raw",
    [
        "https://u:SIGSECRET@[::1/x?sig=TOKSECRET",  # unclosed IPv6 bracket: urlsplit raises
        "http://[bad/x?token=TOKSECRET",
        "https://a？b.example/x?sig=SIGSECRET",  # NFKC-normalizes to '?': urlsplit raises
    ],
)
def test_display_url_never_raises_and_falls_back_to_a_fixed_placeholder(raw: str) -> None:
    assert display_url(raw) == UNPARSEABLE
    assert _leaks(display_url(raw)) == []


# -- the run log and its spans -------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_omitted_optional_signed_source_logs_no_query_or_fragment(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder()
    text = f"(src={SIGNED_TXT};accept=image/png;optional, 'kept')!'d'"
    with caplog.at_level(logging.DEBUG):
        assert await run(text, _web(), process=_Model(), observer=recorder) == "ok"
    warns = [e.body for e in recorder.events if isinstance(e, Log) and e.severity == "WARN"]
    assert f"optional attachment source '{TXT}?<redacted>#<redacted>' omitted" in warns
    # every event (span starts/ends, their attributes, every log line) and the stdlib log
    assert _leaks(repr(recorder.events)) == []
    assert _leaks(caplog.text) == []


# -- caller-facing and internal error texts ------------------------------------------------


@pytest.mark.asyncio
async def test_a_wrong_type_signed_attachment_error_names_only_host_and_path() -> None:
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={SIGNED_TXT};accept=image/png)!'d'", _web(), process=_Model())
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert f"'{TXT}?<redacted>#<redacted>'" in str(caught.value)
    assert _leaks(_error_text(caught.value)) == []


class _TextOnly:
    async def fetch(self, target: str, *, relative: bool) -> str:
        return "text"


@pytest.mark.asyncio
async def test_a_signed_attachment_on_a_text_only_adapter_hides_its_query() -> None:
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={SIGNED_IMG};accept=image/png)!'d'", _TextOnly(), process=_Model())
    assert caught.value.code == ErrorCode.UNSUPPORTED_MODE
    assert IMG in str(caught.value)
    assert _leaks(_error_text(caught.value)) == []


@pytest.mark.asyncio
async def test_a_signed_attachment_under_a_model_collection_is_not_static_without_its_query() -> (
    None
):
    text = f"((src='a')!'list'*(src={SIGNED_IMG};accept=image/png)!'d')!'r'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, _web(), process=_Model())
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert IMG in str(caught.value)
    assert _leaks(_error_text(caught.value)) == []


@pytest.mark.asyncio
async def test_a_prebuilt_graph_signed_attachment_is_not_static_without_its_query() -> None:
    graph = compile_expression(f"(src={SIGNED_IMG};accept=image/png)!'d'")
    with pytest.raises(ResolutionError) as caught:
        await run(graph, _web(), process=_Model())
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert IMG in str(caught.value)
    assert _leaks(_error_text(caught.value)) == []


@pytest.mark.asyncio
async def test_a_non_literal_relative_attachment_target_hides_its_query() -> None:
    text = "(src=/files/$name?sig=SIGSECRET;accept=image/png)!'d'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, _web(), process=_Model())
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert "/files/$name?<redacted>" in str(caught.value)
    assert _leaks(_error_text(caught.value)) == []


def test_an_invalid_guard_value_on_a_signed_source_hides_its_query() -> None:
    with pytest.raises(ParseError) as caught:
        compile_expression(f"(src={SIGNED_IMG};accept=image/png;t=abc)!'d'")
    assert "invalid ;t='abc'" in str(caught.value)
    assert IMG in str(caught.value)
    assert _leaks(_error_text(caught.value)) == []


def test_a_bytes_fetch_without_a_bytes_port_hides_the_target_query() -> None:
    error = no_bytes_port(SIGNED_IMG)
    assert error.code == ErrorCode.UNSUPPORTED_MODE
    assert IMG in str(error)
    assert _leaks(_error_text(error)) == []


@pytest.mark.asyncio
async def test_a_flight_that_stores_nothing_raises_without_the_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stores_nothing(self: object, inputs: object, ctx: object) -> str:
        return ""

    monkeypatch.setattr(_materialize._AttachmentFetchNode, "resolve", stores_nothing)
    with pytest.raises(RuntimeError) as caught:
        await run(f"(src={SIGNED_IMG};accept=image/png)!'d'", _web(), process=_Model())
    assert "stored nothing" in str(caught.value)
    assert IMG in str(caught.value)
    assert _leaks(_error_text(caught.value)) == []


@pytest.mark.asyncio
async def test_a_collection_admission_that_stores_nothing_raises_without_the_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stores_nothing(self: object, inputs: object, ctx: object) -> str:
        return ""

    monkeypatch.setattr(_materialize._CollectionFetchNode, "resolve", stores_nothing)
    text = f"({SIGNED_ROWS}*(src={IMG};accept=image/png)!'d')!'r'"
    with pytest.raises(RuntimeError) as caught:
        await run(text, _web(), process=_Model())
    assert "stored nothing" in str(caught.value)
    assert ROWS in str(caught.value)
    assert _leaks(_error_text(caught.value)) == []
