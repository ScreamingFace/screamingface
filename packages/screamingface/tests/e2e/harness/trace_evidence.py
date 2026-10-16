"""Trace-evidence checks shared by the correlation ladder and the workbench (OME-938, OME-1105).

One implementation, two log sources: files on disk here, pod logs in the cloud targets.
"""

from __future__ import annotations

import re

TRACE_ID = re.compile(r"\b[0-9a-f]{32}\b")
CALL_ID_MARK = "gateway_call_id="


def unattributed_gateway_lines(text: str) -> tuple[int, list[str]]:
    """(identified-line count, lines in the request window that carry no call id).

    The window runs from the first to the last identified line: startup/shutdown lines belong
    to no request and are outside it (see rung 3's docstring for why).
    """

    lines = [ln for ln in text.splitlines() if ln.strip()]
    identified = [i for i, ln in enumerate(lines) if CALL_ID_MARK in ln]
    if not identified:
        return 0, []
    window = lines[identified[0] : identified[-1] + 1]
    return len(identified), [ln for ln in window if CALL_ID_MARK not in ln]
