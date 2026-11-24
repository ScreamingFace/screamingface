"""OME-1942 review (PR #1893): the default filename follows the normalized media type.

WHY a separate file: ``test_attachment_parts.py`` carries an owner-approved, byte-pinned edit
(``.claude/test-change-approvals/OME-1942.json``); these regressions are new tests, so they live
here and leave that approval intact.
"""

from __future__ import annotations

import pytest
from test_attachment_parts import _PDF_BYTES, _PDF_URI, _digest

from screamingface_engine.world.attachment_parts import attachment_parts
from url4 import Attachment

pytestmark = pytest.mark.asyncio


def _pdf_typed(media_type: str) -> Attachment:
    return Attachment(digest=_digest(_PDF_BYTES), media_type=media_type, body=_PDF_BYTES)


async def test_a_mixed_case_parameterized_pdf_type_still_gets_attachment_pdf() -> None:
    [part] = await attachment_parts([_pdf_typed("Application/PDF; charset=binary")])

    assert part == {
        "type": "file",
        "file": {"file_data": _PDF_URI, "filename": "attachment.pdf"},
    }


async def test_padding_around_the_pdf_type_still_gets_attachment_pdf() -> None:
    [part] = await attachment_parts([_pdf_typed("  APPLICATION/pdf  ")])

    assert part == {
        "type": "file",
        "file": {"file_data": _PDF_URI, "filename": "attachment.pdf"},
    }
