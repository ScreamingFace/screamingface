"""The server's own verdict on what a report carries (spec §4)."""

from __future__ import annotations

from .content import CONTENT, ENVELOPE, Classification, Verdict, classify_report, scan_text

__all__ = [
    "CONTENT",
    "ENVELOPE",
    "Classification",
    "Verdict",
    "classify_report",
    "scan_text",
]
