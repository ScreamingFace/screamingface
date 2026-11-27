"""Case files by blob reference: the Engine side's per-run state and part swap (OME-1970 PR 7).

FEATURE: a **Case** file (a picture or PDF) used to ride every model call inline as base64. Now the
Engine uploads each file to the gateway once per run and each call carries a **blob reference**,
``blob:sha256/<64 hex>``, the SHA-256 of the file's bytes. These tests drive
`world.case_file_refs` against a stand-in uploader; the connector-level tests against a fake
gateway live in ``test_connector_case_file_refs.py``.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import re
from typing import Any

import pytest

from screamingface_engine.world.case_file_refs import (
    current_run_files,
    reference_parts,
    run_case_files,
)

pytestmark = pytest.mark.asyncio

# A tiny PNG-signed file: the gateway reads the type from these leading bytes.
_PNG_BYTES: bytes = b"\x89PNG\r\n\x1a\n" + b"a bar chart"
_PNG_URI: str = "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode("ascii")
_PNG_SHA256: str = hashlib.sha256(_PNG_BYTES).hexdigest()
_PDF_BYTES: bytes = b"%PDF-1.7\n" + b"one page"
_PDF_URI: str = "data:application/pdf;base64," + base64.b64encode(_PDF_BYTES).decode("ascii")
_PDF_SHA256: str = hashlib.sha256(_PDF_BYTES).hexdigest()
_QUESTION: dict[str, Any] = {"type": "text", "text": "What is the tallest bar?"}


class _StandInUploader:
    """Records each upload and answers with the type the gateway would read (or ``None``).

    Stand-in for the gateway's ``PUT /v1/blobs/sha256/{digest}``: ``answer`` is what the route
    returns as ``media_type``; ``None`` means the gateway has no upload route (404/405).
    """

    def __init__(self, answer: str | None = "image/png", *, fail_first: bool = False) -> None:
        self.answer: str | None = answer
        self.fail_first: bool = fail_first
        self.uploads: list[tuple[str, bytes]] = []

    async def upload(self, digest: str, data: bytes) -> str | None:
        """Record the upload, yield once so concurrent callers overlap, then answer."""
        self.uploads.append((digest, data))
        await asyncio.sleep(0.01)
        if self.fail_first and len(self.uploads) == 1:
            raise RuntimeError("the gateway was briefly unreachable")
        return self.answer


def _picture_messages(detail: str = "high") -> list[dict[str, Any]]:
    """A system line, then one user message with a question and one inline PNG."""
    return [
        {"role": "system", "content": "You read charts."},
        {
            "role": "user",
            "content": [
                _QUESTION,
                {"type": "image_url", "image_url": {"url": _PNG_URI, "detail": detail}},
            ],
        },
    ]


async def test_an_inline_picture_becomes_a_reference_part_carrying_its_type_and_size() -> None:
    # STORY: as the gateway, I find the file by its SHA-256 and check the declared type and
    # decoded size against what was uploaded (core/blob_refs.py `RunFiles.require`).
    uploader = _StandInUploader()
    messages: list[dict[str, Any]] = _picture_messages()
    before: list[dict[str, Any]] = copy.deepcopy(messages)
    with run_case_files() as run:
        sent: list[dict[str, Any]] = await reference_parts(messages, uploader, run)

    assert sent == [
        {"role": "system", "content": "You read charts."},
        {
            "role": "user",
            "content": [
                _QUESTION,
                {
                    "type": "image_url",
                    "image_url": {"url": f"blob:sha256/{_PNG_SHA256}", "detail": "high"},
                    "x_media_type": "image/png",
                    "x_size": len(_PNG_BYTES),
                },
            ],
        },
    ]
    # The decoded bytes go up, labelled with their own SHA-256.
    assert uploader.uploads == [(_PNG_SHA256, _PNG_BYTES)]
    # INVARIANT: the caller's messages are not modified; the inline form stays what the frozen
    # copy's request digest and the response cache key hash (decision 2).
    assert messages == before


async def test_a_pdf_part_keeps_its_filename_beside_the_reference() -> None:
    uploader = _StandInUploader("application/pdf")
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                _QUESTION,
                {"type": "file", "file": {"file_data": _PDF_URI, "filename": "report.pdf"}},
            ],
        }
    ]
    with run_case_files() as run:
        sent: list[dict[str, Any]] = await reference_parts(messages, uploader, run)

    assert sent[0]["content"][1] == {
        "type": "file",
        "file": {"file_data": f"blob:sha256/{_PDF_SHA256}", "filename": "report.pdf"},
        "x_media_type": "application/pdf",
        "x_size": len(_PDF_BYTES),
    }


async def test_each_file_uploads_once_per_run_across_concurrent_calls() -> None:
    # STORY: a 5-member Fusion and its synthesizer send the same Case at once; the PDF goes up
    # once, not six times (the 23 Nov gateway pod peaked near 980 MiB doing six inline copies).
    uploader = _StandInUploader()
    with run_case_files() as run:
        sent: list[list[dict[str, Any]]] = await asyncio.gather(
            *(reference_parts(_picture_messages(), uploader, run) for _ in range(6))
        )
        # A later call in the same run, after the upload finished, uploads nothing either.
        await reference_parts(_picture_messages(), uploader, run)

    assert len(uploader.uploads) == 1
    assert {call[1]["content"][1]["image_url"]["url"] for call in sent} == {
        f"blob:sha256/{_PNG_SHA256}"
    }


async def test_a_failed_upload_is_tried_again_by_the_next_call() -> None:
    # WHY: a failure must not be remembered as "uploaded"; the next call would then send a
    # reference the gateway never got, and every later call of the run would fail.
    uploader = _StandInUploader(fail_first=True)
    with run_case_files() as run:
        with pytest.raises(RuntimeError):
            await reference_parts(_picture_messages(), uploader, run)
        sent: list[dict[str, Any]] = await reference_parts(_picture_messages(), uploader, run)

    assert len(uploader.uploads) == 2
    assert sent[1]["content"][1]["image_url"]["url"] == f"blob:sha256/{_PNG_SHA256}"


async def test_no_upload_route_turns_the_whole_run_inline() -> None:
    # STORY: as an Engine pointed at a gateway built before the upload route, my run still works:
    # the first upload finds no route, and every call of the run sends its files inline.
    uploader = _StandInUploader(answer=None)
    with run_case_files() as run:
        first: list[dict[str, Any]] = await reference_parts(_picture_messages(), uploader, run)
        second: list[dict[str, Any]] = await reference_parts(
            _picture_messages("low"), uploader, run
        )

    assert run.inline is True
    assert first == _picture_messages()
    assert second == _picture_messages("low")
    # INVARIANT: the path is chosen once per run; the second call never tries to upload.
    assert len(uploader.uploads) == 1


async def test_a_file_the_gateway_reads_as_another_type_stays_inline() -> None:
    # WHY: the gateway swaps a reference back as `data:<the type it read>;…`, so a Case that
    # labels a PNG as JPEG would reach the provider (and the cache key) changed. That one part
    # keeps today's inline bytes; the run is not switched to inline.
    uploader = _StandInUploader("image/jpeg")
    with run_case_files() as run:
        sent: list[dict[str, Any]] = await reference_parts(_picture_messages(), uploader, run)

    assert sent == _picture_messages()
    assert run.inline is False


async def test_a_data_uri_with_parameters_stays_inline() -> None:
    # WHY: the gateway writes back `data:<type>;base64,…` with no parameters; a part spelled
    # with one would come back different from what the Case holds.
    uri: str = _PNG_URI.replace("data:image/png;", "data:image/png;name=chart.png;")
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [_QUESTION, {"type": "image_url", "image_url": {"url": uri}}]}
    ]
    uploader = _StandInUploader()
    with run_case_files() as run:
        sent: list[dict[str, Any]] = await reference_parts(messages, uploader, run)

    assert sent == messages
    assert uploader.uploads == []


async def test_a_text_only_call_is_returned_as_it_is_with_no_upload() -> None:
    uploader = _StandInUploader()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "Answer briefly."},
        {"role": "user", "content": "What is 6 times 7?"},
    ]
    with run_case_files() as run:
        sent: list[dict[str, Any]] = await reference_parts(messages, uploader, run)

    assert sent == messages
    assert uploader.uploads == []


async def test_two_runs_get_different_tokens_and_no_repr_shows_one() -> None:
    # INVARIANT (decision 3): the token is what keeps another run, which may know the SHA-256,
    # from using this run's file; so each run mints its own, and no log line can carry it.
    assert current_run_files() is None
    with run_case_files() as first:
        assert current_run_files() is first
    with run_case_files() as second:
        pass
    assert current_run_files() is None

    assert first.token != second.token
    # The gateway admits 32 to 256 URL-safe characters (routes/blobs.py `_RUN_TOKEN`).
    assert re.fullmatch(r"[A-Za-z0-9_-]{32,256}", first.token)
    assert first.token not in repr(first)
