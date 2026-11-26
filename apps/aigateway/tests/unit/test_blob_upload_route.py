"""The upload route: one Case file in, stored under the caller and the run's token (OME-1970).

FEATURE: Case files by blob reference (OME-1970, PR 4; decisions 3 and 4).
STORY: as the Engine starting a run, I `PUT` each Case file once, labelled with its SHA-256 and my
run's token; every later model call carries only the reference.
INVARIANT: the route keeps its own 15,000,000-byte cap, not the app-wide 12 MiB one; it refuses
a mismatch, an oversize body and a type outside the five before anything is stored; nothing is
written to disk; no log line or refusal carries the token or the file's bytes.
"""

from __future__ import annotations

import base64
import builtins
import hashlib
import logging
import os
import tempfile
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from aigateway.core.auth.middleware import current_account
from aigateway.core.blob_upload import MAX_BLOB_UPLOAD_BYTES
from aigateway.core.media_store import BlobScope, MediaStore
from aigateway.routes import blobs

CALLER_A = "11111111-1111-1111-1111-111111111111"
CALLER_B = "22222222-2222-2222-2222-222222222222"
# Stand-ins for the random per-run token the Engine mints (`secrets.token_urlsafe(32)`, 43 chars).
TOKEN_RUN_1 = "run1-" + "A" * 38
TOKEN_RUN_2 = "run2-" + "B" * 38
PDF = b"%PDF-1.7\n" + b"the Case's PDF body " * 50
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 50


def _path(digest: str) -> str:
    return f"/v1/blobs/sha256/{digest}"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def store() -> MediaStore:
    return MediaStore(max_bytes=100_000_000, scope_ttl_seconds=600)


@pytest.fixture
def app(store: MediaStore) -> FastAPI:
    """Only the upload route, with the caller named by a test header instead of real auth.

    WHY a stand-in for `current_account`: the subject is the scope the route builds from the
    caller it is given, so two callers are two values of one header here.
    """
    app = FastAPI()
    app.state.media_store = store
    app.include_router(blobs.router)

    def _caller(request: Request) -> Any:
        return SimpleNamespace(id=request.headers.get("X-Test-Caller", CALLER_A))

    app.dependency_overrides[current_account] = _caller
    return app


@pytest.fixture
def blob_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _upload(
    blob_client: TestClient,
    payload: bytes,
    *,
    digest: str | None = None,
    token: str | None = TOKEN_RUN_1,
    caller: str = CALLER_A,
) -> Any:
    headers: dict[str, str] = {"X-Test-Caller": caller}
    if token is not None:
        headers[blobs.RUN_TOKEN_HEADER] = token
    return blob_client.put(
        _path(digest or _digest(payload)),
        content=payload,
        headers=headers,
    )


def test_the_run_token_header_follows_the_gateways_header_convention() -> None:
    assert blobs.RUN_TOKEN_HEADER == "X-AIGW-Run-Token"


def test_an_upload_is_stored_as_base64_under_the_caller_and_the_runs_token(
    blob_client: TestClient, store: MediaStore
) -> None:
    resp = _upload(blob_client, PDF)

    assert resp.status_code == 201, resp.text
    assert resp.json() == {
        "ref": f"blob:sha256/{_digest(PDF)}",
        "media_type": "application/pdf",
        "size_bytes": len(PDF),
    }
    stored = store.get(BlobScope.of(CALLER_A, TOKEN_RUN_1), _digest(PDF))
    assert stored is not None
    assert stored.base64_text == base64.b64encode(PDF).decode("ascii")
    assert stored.media_type == "application/pdf"
    assert stored.size_bytes == len(PDF)


def test_a_lookup_with_another_runs_token_or_no_token_gets_nothing(
    blob_client: TestClient, store: MediaStore
) -> None:
    assert _upload(blob_client, PDF).status_code == 201

    assert store.get(BlobScope.of(CALLER_A, TOKEN_RUN_2), _digest(PDF)) is None
    assert store.get(BlobScope.of(CALLER_A, None), _digest(PDF)) is None
    assert store.get(BlobScope.of(CALLER_B, TOKEN_RUN_1), _digest(PDF)) is None


def test_uploading_the_same_file_twice_is_accepted(blob_client: TestClient) -> None:
    # WHY: the Engine uploads again after the gateway dropped a file (PR 8); a file still held
    # must not turn that retry into a failure.
    assert _upload(blob_client, PNG).status_code == 201
    assert _upload(blob_client, PNG).status_code == 201


def test_bytes_that_do_not_hash_to_the_named_digest_are_refused(
    blob_client: TestClient, store: MediaStore
) -> None:
    resp = _upload(blob_client, PDF, digest=_digest(b"another file"))

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "blob_digest_mismatch"
    assert store.held_bytes == 0


def test_a_type_outside_the_five_is_refused(blob_client: TestClient, store: MediaStore) -> None:
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'/>"

    resp = _upload(blob_client, svg)

    assert resp.status_code == 415, resp.text
    assert resp.json()["detail"]["code"] == "blob_unsupported_media_type"
    assert store.held_bytes == 0


def test_a_declared_length_over_the_cap_is_refused_before_reading(
    blob_client: TestClient, store: MediaStore
) -> None:
    payload: bytes = b"%PDF-" + b"x" * MAX_BLOB_UPLOAD_BYTES

    resp = _upload(blob_client, payload)

    assert resp.status_code == 413, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "blob_too_large"
    assert detail["limit_bytes"] == 15_000_000
    assert resp.headers["connection"] == "close"
    assert store.held_bytes == 0


def test_a_chunked_body_over_the_cap_is_refused(blob_client: TestClient, store: MediaStore) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"%PDF-1.7\n"
        for _ in range(16):
            yield b"x" * 1_000_000

    resp = blob_client.put(
        _path("0" * 64),
        content=chunks(),
        headers={blobs.RUN_TOKEN_HEADER: TOKEN_RUN_1},
    )

    assert resp.status_code == 413, resp.text
    assert resp.json()["detail"]["code"] == "blob_too_large"
    assert store.held_bytes == 0


@pytest.mark.parametrize("digest", ["abc", "G" * 64, "A" * 64, "0" * 63, "0" * 65])
def test_a_malformed_digest_is_refused(blob_client: TestClient, digest: str) -> None:
    # WHY uppercase is refused: the reference spelling is lowercase hex, so one file has one
    # name; accepting both would store the same file under two keys.
    resp = _upload(blob_client, PNG, digest=digest)

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "invalid_request"


@pytest.mark.parametrize("token", [None, "", "short", "has space " + "x" * 40, "x" * 257])
def test_an_upload_without_a_usable_run_token_is_refused(
    blob_client: TestClient, store: MediaStore, token: str | None
) -> None:
    resp = _upload(blob_client, PNG, token=token)

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "invalid_request"
    assert store.held_bytes == 0
    if token:
        assert token not in resp.text


class _WriteOpens:
    """Every call that would open a file for writing, recorded instead of judged afterwards."""

    def __init__(self) -> None:
        self.calls: list[str] = []


@pytest.fixture
def write_opens(monkeypatch: pytest.MonkeyPatch) -> _WriteOpens:
    """Record any attempt to open a file for writing or create a temporary file.

    WHY these entry points: Python file writes go through `open` (builtins and io share it) or
    `os.open`; Starlette spools multipart uploads to `tempfile.SpooledTemporaryFile`, the one
    disk path a web framework takes on its own.
    """
    seen = _WriteOpens()
    real_open = builtins.open
    real_os_open = os.open
    write_flags: int = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in "wax+"):
            seen.calls.append(f"open({file!r}, {mode!r})")
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & write_flags:
            seen.calls.append(f"os.open({path!r})")
        return real_os_open(path, flags, *args, **kwargs)

    def refused_temp(*args: Any, **kwargs: Any) -> Any:
        seen.calls.append("tempfile")
        raise AssertionError("an upload created a temporary file")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    for name in ("SpooledTemporaryFile", "TemporaryFile", "NamedTemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, refused_temp)
    return seen


def test_nothing_is_written_to_disk(blob_client: TestClient, write_opens: _WriteOpens) -> None:
    big: bytes = b"%PDF-1.7\n" + b"y" * 3_000_000

    assert _upload(blob_client, big).status_code == 201
    assert _upload(blob_client, b"<svg/>").status_code == 415

    assert write_opens.calls == []


class _Records(logging.Handler):
    """Collect every record the gateway's logger tree emits, at any level."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def records() -> Iterator[_Records]:
    """Capture the `aigateway` tree directly: `logs.configure` turns its propagation off."""
    handler = _Records()
    logger = logging.getLogger("aigateway")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def test_no_log_line_or_refusal_carries_the_token_or_the_files_bytes(
    blob_client: TestClient, records: _Records, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token_hash: str = hashlib.sha256(TOKEN_RUN_1.encode("ascii")).hexdigest()
    pdf_base64: str = base64.b64encode(PDF).decode("ascii")
    answers: list[str] = [
        _upload(blob_client, PDF).text,
        _upload(blob_client, PDF, digest=_digest(b"other")).text,
        _upload(blob_client, b"<svg>secret picture text</svg>").text,
        _upload(blob_client, b"%PDF-" + b"z" * MAX_BLOB_UPLOAD_BYTES).text,
    ]

    lines: list[str] = records.lines + [record.getMessage() for record in caplog.records]
    assert lines, "the route logs what it stored and what it refused"
    for text in lines + answers:
        assert TOKEN_RUN_1 not in text
        assert token_hash not in text
        assert "the Case's PDF body" not in text
        assert pdf_base64[:40] not in text
        assert "secret picture text" not in text


def test_the_real_app_mounts_the_route_outside_the_app_wide_body_cap(
    authenticated_client: TestClient,
) -> None:
    # The app-wide cap is 2,048 bytes here (`small_app_cap`, autouse, so it is set before the
    # app is built); a 4,096-byte upload still passes, because the upload route keeps its own
    # 15,000,000-byte cap, while a 4,096-byte chat body is still refused.
    payload: bytes = b"\x89PNG\r\n\x1a\n" + b"q" * 4088

    resp = authenticated_client.put(
        _path(_digest(payload)),
        content=payload,
        headers={blobs.RUN_TOKEN_HEADER: TOKEN_RUN_1},
    )

    assert resp.status_code == 201, resp.text
    chat = authenticated_client.post(
        "/v1/chat/completions",
        content=b"x" * 4096,
        headers={"content-type": "application/json"},
    )
    assert chat.status_code == 413
    assert chat.json()["detail"]["code"] == "request_too_large"


@pytest.fixture(autouse=True)
def small_app_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2,048-byte app-wide body cap for the real-app test; the stand-in app ignores it."""
    monkeypatch.setenv("AIGW_MAX_REQUEST_BYTES", "2048")
