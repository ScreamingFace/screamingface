"""Optional notebook browser bridge; sends refresh events, never credentials."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def create_refresh_bridge(callback: Callable[[], None]) -> Any:
    try:
        import anywidget
    except ImportError:
        # WHY: existing ipywidgets notebooks can still connect and refresh manually.
        return None
    import traitlets

    class CreditRefresh(anywidget.AnyWidget):
        _esm = Path(__file__).with_name("credit_refresh.js").read_text()
        active = traitlets.Bool(True).tag(sync=True)

    widget = CreditRefresh()
    widget.layout.height = "1px"
    widget.layout.min_height = "1px"

    def receive(_: Any, message: Any, buffers: Any) -> None:
        if not widget.active or not isinstance(message, dict) or message.get("type") != "refresh":
            return
        try:
            callback()
        finally:
            widget.send({"type": "refreshed"})

    widget.on_msg(receive)
    return widget
