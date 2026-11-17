"""The image input matrix's known-answer fixtures (spec §3.3) match their manifest.

WHY these checks: the notebook fetches each fixture from a commit-pinned
``cdn.jsdelivr.net/gh`` URL and verifies its sha256 against ``manifest.json`` before any
model call. A manifest that drifts from the committed bytes would turn every url4 cell into a
setup error; a file whose bytes are not the media type it claims would test the wrong decoder.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Final

import pytest

FIXTURES: Final = Path(__file__).parent / "fixtures" / "image_input"
MAX_BYTES: Final = 64 * 1024
MEDIA_TYPES: Final = ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf")


def _repo_root() -> Path:
    # A worktree's `.git` is a file, a clone's a directory: `exists` covers both.
    return next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())


def _manifest() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def _magic_ok(media_type: str, head: bytes) -> bool:
    checks = {
        "image/png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": head.startswith(b"\xff\xd8\xff"),
        "image/gif": head.startswith(b"GIF89a"),
        "image/webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        "application/pdf": head.startswith(b"%PDF-"),
    }
    return checks[media_type]


def test_the_five_media_types_are_each_covered_once() -> None:
    assert sorted(e["media_type"] for e in _manifest()) == sorted(MEDIA_TYPES)


@pytest.mark.parametrize("entry", _manifest(), ids=lambda e: e["media_type"])
def test_entry_matches_its_committed_bytes(entry: dict[str, Any]) -> None:
    # `path` is repo-relative: it is the tail of the jsDelivr URL.
    path = _repo_root() / entry["path"]
    assert path.parent == FIXTURES.resolve(), entry["path"]
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert len(data) == entry["bytes"]
    assert len(data) < MAX_BYTES
    assert _magic_ok(entry["media_type"], data[:16])
    assert entry["expected"].strip()


def test_pictures_carry_the_token_and_the_pdf_the_code_word() -> None:
    expected = {e["media_type"]: e["expected"] for e in _manifest()}
    assert {expected[m] for m in MEDIA_TYPES if m.startswith("image/")} == {"7392"}
    assert expected["application/pdf"] == "HELIOTROPE"


def test_pdf_is_text_not_an_embedded_picture() -> None:
    """A PDF-capable model must READ text: no image XObject, the word in a show-text operator."""
    data = (FIXTURES / "codeword.pdf").read_bytes()
    assert b"/Image" not in data
    assert re.search(rb"\(HELIOTROPE\)\s*Tj", data)
