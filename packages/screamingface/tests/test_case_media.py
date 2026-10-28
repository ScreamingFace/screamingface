"""Open a Case's picture or file from its Case Result, checked against the placeholder (OME-1271).

FEATURE (OME-1271, PR 5): a Case Result shows each picture as a placeholder (type, size,
sha256); the run parked the bytes in the engine's result store under that sha256.
``case.media`` lists them with no network call, ``sf.fetch_media`` opens one, and the report
browser gives each a button: Show picture, or Save file.
STORY: as a researcher reading why Case 17 was marked wrong, I click Show picture and see the
figure the model saw, or a plain reason why I can't.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
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


def _browser(case_input: str, tmp_path: Path, monkeypatch) -> Any:
    """A live report browser over one Case whose input is ``case_input``."""

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = large_report(1)
    owner = replace(
        source.candidates[0],
        cases=tuple(replace(case, input=case_input) for case in source.candidates[0].cases),
    )
    return ReportBrowser(sf.Report(benchmark=source.benchmark, case_count=1, candidates=[owner]))


def _click(browser: Any, label: str) -> None:
    """Click the first in-place button named ``label``, the way ipyevents reports it: by id."""

    found = re.search(rf"id='(sf-media-[0-9a-f]+)'[^>]*>[^<]*{label}</button>", browser.cases.value)
    assert found, f"no {label} button in the page"
    browser._select_case({"target": {"id": found.group(1)}})


def test_show_picture_draws_the_picture_in_place_of_its_line(tmp_path: Path, monkeypatch) -> None:
    # WHY in place: the researcher reads the question and its picture together, so the button
    # sits on the placeholder line inside the Case card, and the picture replaces the button.
    fetched: list[CaseMedia] = []

    def fetch(media: CaseMedia) -> FetchedMedia:
        fetched.append(media)
        return _fetch_from({_PNG_SHA256: _PNG_BYTES})(media)

    monkeypatch.setattr("screamingface._default_client.fetch_media", fetch)
    browser = _browser(_ENGINE_ECHO, tmp_path, monkeypatch)
    question: str = browser.cases.value.split("<div class='sf-pane__q'>", 1)[1].split("</div>")[0]

    assert re.search(r">🖼 Show picture</button> image/png · 8 B · sha256 4c4b6a3b", question)
    # WHY: pictures are fetched one at a time, on request; a page of Cases downloads none.
    assert fetched == [] and "sf-media-img" not in browser.cases.value
    _click(browser, "Show picture")

    drawn: str = base64.b64encode(_PNG_BYTES).decode("ascii")
    assert fetched == [_PICTURE]
    assert f"<img class='sf-media-img' src='data:image/png;base64,{drawn}'" in browser.cases.value
    assert "Show picture" not in browser.cases.value


def _picture_after(text: str) -> str:
    """A Case whose message is ``text`` first and the picture after it, as MMMU's often are."""

    return json.dumps(
        {
            "schema": "screamingface.candidate-input.v2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": _PNG_PLACEHOLDER}},
                    ],
                }
            ],
        }
    )


@pytest.mark.parametrize(
    ("text", "button_first"),
    [
        ("Which graph matches the table? <image 1>", False),
        # WHY 12,000: past the card's 10,000-character clip, so the picture's own line is cut.
        ("x" * 12_000, True),
    ],
    ids=["after-the-text", "line-cut-off"],
)
def test_a_picture_after_the_text_keeps_a_button(
    text: str, button_first: bool, tmp_path: Path, monkeypatch
) -> None:
    # WHY: LAB-Bench puts the picture first, but MMMU and HLE put it after the question; the
    # button follows the picture, and one whose line the card cut off moves to the top.
    browser = _browser(_picture_after(text), tmp_path, monkeypatch)
    question: str = browser.cases.value.split("<div class='sf-pane__q'>", 1)[1]
    button: int = question.find("Show picture</button>")

    assert button >= 0
    assert (button < question.find(text[:40])) is button_first


def test_save_file_writes_the_file_and_says_where(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "screamingface._default_client.fetch_media", _fetch_from({_PDF_SHA256: _PDF_BYTES})
    )
    browser = _browser(_ENGINE_FILE_ECHO, tmp_path, monkeypatch)
    _click(browser, "Save file")

    saved: Path = (browser.directory / "methods.pdf").resolve()
    assert saved.read_bytes() == _PDF_BYTES
    assert str(saved) in browser.media.notice.value
    assert browser.media.notice in browser.case_box.children


def test_a_picture_the_engine_no_longer_holds_shows_the_reason(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screamingface._default_client.fetch_media", _fetch_from({}))
    browser = _browser(_ENGINE_ECHO, tmp_path, monkeypatch)
    _click(browser, "Show picture")

    assert "no longer holds it" in browser.media.notice.value
    assert "sf-media-img" not in browser.cases.value
    assert "Show picture</button>" in browser.cases.value  # still there, to try again


def test_a_file_whose_name_cannot_be_written_shows_the_reason(tmp_path: Path, monkeypatch) -> None:
    # WHY: the Benchmark names its files, and a name with a NUL byte can't be written on any
    # system; the researcher reads why in the notice, not a traceback.
    monkeypatch.setattr(
        "screamingface._default_client.fetch_media", _fetch_from({_PDF_SHA256: _PDF_BYTES})
    )
    unwritable: str = _ENGINE_FILE_ECHO.replace("methods.pdf", "methods\\u0000.pdf")
    browser = _browser(unwritable, tmp_path, monkeypatch)
    _click(browser, "Save file")

    assert "null byte" in browser.media.notice.value
    assert 'role="alert"' in browser.media.notice.value


def test_only_the_most_recently_opened_pictures_stay_drawn(tmp_path: Path, monkeypatch) -> None:
    # WHY: each drawn picture is kept as base64 in the kernel, and clicking through FigQA's 181
    # figures would hold about 320 MB; past the bound, the one opened longest ago goes back to
    # its button. A bound of 1 here, so two pictures are enough to cross it.
    import ipywidgets

    from screamingface._ui import media_panel

    other_bytes: bytes = _PNG_BYTES + b"\x00"
    other = CaseMedia(
        kind="image",
        media_type="image/png",
        size=len(other_bytes),
        sha256=hashlib.sha256(other_bytes).hexdigest(),
    )
    monkeypatch.setattr(
        "screamingface._default_client.fetch_media",
        _fetch_from({_PNG_SHA256: _PNG_BYTES, other.sha256: other_bytes}),
    )
    monkeypatch.setattr(media_panel, "_KEPT_PICTURES", 1)
    panel = media_panel.MediaPanel(ipywidgets, folder=tmp_path, redraw=lambda: None)

    panel.open(_PICTURE)
    panel.open(other)

    assert panel._control(other, "").startswith("<img")
    assert panel._control(_PICTURE, "").startswith("<button")


def test_a_static_report_shows_the_placeholder_without_a_button() -> None:
    # WHY: a static report has no kernel to answer a click, so a button there would do nothing.
    from screamingface._ui.report_view import cases_page_html

    report = sf.Report(
        benchmark=large_report(1).benchmark,
        case_count=1,
        candidates=[replace(large_report(1).candidates[0], cases=(_case(_ENGINE_ECHO),))],
    )
    page: str = cases_page_html(report, [(report.candidates[0], report.candidates[0].cases[0])])

    assert "image/png · 8 B · sha256 4c4b6a3b" in page
    assert "<button" not in page
