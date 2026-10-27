"""Open a Case's picture or file from its Case Result, checked against the placeholder (OME-1271).

FEATURE (OME-1271, PR 5): a Case Result shows each picture as a placeholder (type, size,
sha256); the run parked the bytes in the engine's result store under that sha256.
``case.media`` lists them with no network call, ``sf.fetch_media`` opens one, and the report
browser gives each a button: Show picture, or Save file.
STORY: as a researcher reading why Case 17 was marked wrong, I click Show picture and see the
figure the model saw, or a plain reason why I can't.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_accounting_breakdown import replace
from test_report_browser import large_report

import screamingface as sf
from screamingface.case_result import CaseGrade, CaseResult
from screamingface.media import CaseMedia, FetchedMedia, case_media

# The 8-byte PNG signature and the 8 bytes b"%PDF-1.4", with the sha256 the engine pins for
# them (test_media_placeholder_conformance.py, test_echoed_input.py).
_PNG_BYTES = b"\x89PNG\r\n\x1a\n"
_PNG_SHA256 = "4c4b6a3be1314ab86138bef4314dde022e600960d8689a2c8f8631802d20dab6"
_PDF_BYTES = b"%PDF-1.4"
_PDF_SHA256 = "e16fa5d9b51928755db85b917f0297babaf22c7a47e97d9212adab56e61ba04e"
# The engine's echo of a picture Case and of a named PDF, in the compact shape #1558 writes.
_PNG_PLACEHOLDER = {
    "placeholder": "image",
    "media_type": "image/png",
    "size": 8,
    "sha256": _PNG_SHA256,
}
_ENGINE_ECHO = json.dumps(
    {
        "schema": "screamingface.candidate-input.v2",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is shown?"},
                    {"type": "image_url", "image_url": {"url": _PNG_PLACEHOLDER}},
                ],
            }
        ],
    },
    separators=(",", ":"),
)
_ENGINE_FILE_ECHO = json.dumps(
    {
        "schema": "screamingface.candidate-input.v2",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "file_data": {
                                "placeholder": "file",
                                "media_type": "application/pdf",
                                "size": 8,
                                "sha256": _PDF_SHA256,
                                "filename": "methods.pdf",
                            },
                            "filename": "methods.pdf",
                        },
                    }
                ],
            }
        ],
    },
    separators=(",", ":"),
)
_PICTURE = CaseMedia(kind="image", media_type="image/png", size=8, sha256=_PNG_SHA256)
_PDF = CaseMedia(
    kind="file", media_type="application/pdf", size=8, sha256=_PDF_SHA256, filename="methods.pdf"
)


def _engine(store: dict[str, bytes], requests: list[httpx.Request]) -> httpx.MockTransport:
    """A stand-in engine: mints a token and serves ``store`` at ``/artifacts/{sha256}``."""

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "capability"})
        held: bytes | None = store.get(request.url.path.removeprefix("/artifacts/"))
        return httpx.Response(404) if held is None else httpx.Response(200, content=held)

    return httpx.MockTransport(respond)


def _client(store: dict[str, bytes], requests: list[httpx.Request]) -> sf.Client:
    """A Client whose engine is the stand-in above."""

    return sf.Client(
        engine_url="http://engine.test",
        scoreboard_url="http://scoreboard.test",
        http_transport=_engine(store, requests),
        save_results=False,
    )


# --- what a Case lists --------------------------------------------------------------------


def test_a_case_lists_the_picture_its_engine_echo_names() -> None:
    assert case_media(_ENGINE_ECHO) == (_PICTURE,)
    assert case_media(_ENGINE_FILE_ECHO) == (_PDF,)


def test_a_case_from_an_older_engine_measures_its_inline_picture() -> None:
    # WHY: a result made before the engine echoed placeholders still carries the data: URI;
    # it lists the same picture, with the sha256 the store would name it by.
    inline: str = _ENGINE_ECHO.replace(
        json.dumps(_PNG_PLACEHOLDER, separators=(",", ":")), '"data:image/png;base64,iVBORw0KGgo="'
    )
    assert case_media(inline) == (_PICTURE,)


@pytest.mark.parametrize(
    "case_input",
    [
        "What is 6 times 7?",
        '{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user","content":"Hi"}]}',
        "[Case input not shown: message 0 part 1: expected an inline data: URI]",
    ],
    ids=["plain prompt", "v1 conversation", "refused Case line"],
)
def test_a_text_case_lists_nothing(case_input: str) -> None:
    assert case_media(case_input) == ()


# --- fetching one -------------------------------------------------------------------------


def test_fetch_media_returns_the_bytes_the_placeholder_names() -> None:
    requests: list[httpx.Request] = []
    with _client({_PNG_SHA256: _PNG_BYTES}, requests) as client:
        fetched: FetchedMedia = client.fetch_media(_PICTURE)

    assert fetched.data == _PNG_BYTES
    artifact: httpx.Request = requests[-1]
    assert artifact.url.path == f"/artifacts/{_PNG_SHA256}"
    assert artifact.headers["URL4-Capability"] == "capability"


def test_a_picture_the_store_has_expired_fails_by_name() -> None:
    with _client({}, []) as client, pytest.raises(sf.MediaUnavailableError) as raised:
        client.fetch_media(_PICTURE)

    assert raised.value.code == "media_not_kept"
    assert "Run the Case again" in raised.value.message


@pytest.mark.parametrize(
    "served",
    [b"\x89PNG\r\n\x1a\x00", _PNG_BYTES + b"!"],
    ids=["same size, other bytes", "more bytes than the placeholder"],
)
def test_bytes_that_are_not_the_placeholders_are_never_returned(served: bytes) -> None:
    # INVARIANT: a picture opened from a result is the one the model saw, or nothing.
    with (
        _client({_PNG_SHA256: served}, []) as client,
        pytest.raises(sf.MediaUnavailableError) as raised,
    ):
        client.fetch_media(_PICTURE)

    assert raised.value.code == "media_integrity_mismatch"


def test_a_malformed_sha256_is_refused_before_any_request() -> None:
    # INVARIANT: a placeholder can never steer the fetch to another path.
    requests: list[httpx.Request] = []
    steering = CaseMedia(kind="image", media_type="image/png", size=8, sha256="../token")

    with _client({}, requests) as client, pytest.raises(sf.MediaUnavailableError) as raised:
        client.fetch_media(steering)

    assert raised.value.code == "media_reference_invalid"
    assert requests == []


# --- showing and saving -------------------------------------------------------------------


def test_a_fetched_picture_shows_inline_and_a_file_shows_its_line() -> None:
    picture: dict[str, object] = FetchedMedia(_PICTURE, _PNG_BYTES)._repr_mimebundle_()
    pdf: dict[str, object] = FetchedMedia(_PDF, _PDF_BYTES)._repr_mimebundle_()

    assert picture["image/png"] == _PNG_BYTES
    assert pdf == {"text/plain": "methods.pdf · application/pdf · 8 B · sha256 e16fa5d9…"}


def test_save_into_a_folder_uses_the_files_own_name(tmp_path: Path) -> None:
    saved_pdf: Path = FetchedMedia(_PDF, _PDF_BYTES).save(tmp_path)
    saved_png: Path = FetchedMedia(_PICTURE, _PNG_BYTES).save(tmp_path)

    assert saved_pdf == (tmp_path / "methods.pdf").resolve()
    assert saved_png.name == f"{_PNG_SHA256[:12]}.png"
    assert hashlib.sha256(saved_pdf.read_bytes()).hexdigest() == _PDF_SHA256


# --- the report browser's buttons ---------------------------------------------------------


def _case(case_input: str) -> CaseResult:
    """A scored Case Result whose input is ``case_input``, as the engine published it."""

    return CaseResult(
        case_id=1,
        input=case_input,
        output="a bar chart",
        finish_reason="stop",
        grade=CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )


def _fetch_from(store: dict[str, bytes]) -> Callable[[CaseMedia], FetchedMedia]:
    """A fetch that answers from ``store`` the way the Client would, or fails by name."""

    def fetch(media: CaseMedia) -> FetchedMedia:
        if media.sha256 not in store:
            raise sf.MediaUnavailableError("The engine no longer holds it", code="media_not_kept")
        return FetchedMedia(media, store[media.sha256])

    return fetch


def test_a_picture_gets_show_picture_and_a_file_gets_save_file(tmp_path: Path) -> None:
    import ipywidgets as widgets

    from screamingface._ui.media_panel import MediaPanel

    panel = MediaPanel(
        widgets,
        folder=tmp_path,
        fetch=_fetch_from({_PNG_SHA256: _PNG_BYTES, _PDF_SHA256: _PDF_BYTES}),
    )
    both: dict[str, Any] = json.loads(_ENGINE_ECHO)
    both["messages"][0]["content"].extend(json.loads(_ENGINE_FILE_ECHO)["messages"][0]["content"])
    panel.show(_case(json.dumps(both)))
    show_picture, save_file = (row.children[0] for row in panel.rows.children)

    assert (show_picture.description, save_file.description) == ("Show picture", "Save file")
    show_picture.click()
    assert panel.picture.children[0].value == _PNG_BYTES
    save_file.click()
    assert (tmp_path / "methods.pdf").read_bytes() == _PDF_BYTES
    assert str((tmp_path / "methods.pdf").resolve()) in panel.notice.value


def test_a_picture_the_engine_no_longer_holds_shows_the_reason(tmp_path: Path) -> None:
    import ipywidgets as widgets

    from screamingface._ui.media_panel import MediaPanel

    panel = MediaPanel(widgets, folder=tmp_path, fetch=_fetch_from({}))
    panel.show(_case(_ENGINE_ECHO))
    panel.rows.children[0].children[0].click()

    assert "no longer holds it" in panel.notice.value
    assert panel.picture.children == ()
    assert not panel.rows.children[0].children[0].disabled


def test_the_report_browser_lists_the_focused_cases_media(tmp_path: Path, monkeypatch) -> None:
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = large_report(1)
    owner = replace(
        source.candidates[0],
        cases=tuple(replace(case, input=_ENGINE_ECHO) for case in source.candidates[0].cases),
    )
    browser = ReportBrowser(sf.Report(benchmark=source.benchmark, case_count=1, candidates=[owner]))

    assert [row.children[0].description for row in browser.media.rows.children] == ["Show picture"]
    assert browser.media.widget in browser.case_box.children
