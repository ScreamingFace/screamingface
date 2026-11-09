"""Plain-text helpers shared by the notebook report views.

WHY a leaf module: report_view imports combine_view, so a helper both use lives here, not in
either of them (an import cycle).
"""

from __future__ import annotations


def short(value: str, keep: int = 12) -> str:
    """``value`` when it has at most ``keep`` characters, else its first ``keep`` and "…"."""
    return value if len(value) <= keep else f"{value[:keep]}…"


__all__: list[str] = []
