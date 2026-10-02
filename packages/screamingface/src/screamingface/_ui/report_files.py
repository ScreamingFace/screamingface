"""File-backed report downloads without embedding their contents in widget state."""

from __future__ import annotations

import os
from html import escape
from pathlib import Path
from urllib.parse import quote


def download_link(path: Path, label: str) -> str:
    url = _served_url(path)
    if url is None:
        return f"<p>{escape(label)} saved to <code>{escape(str(path))}</code></p>"
    return (
        f'<div class="sf-browser-links"><a href="{escape(url, quote=True)}" '
        f'download="{escape(path.name, quote=True)}">{escape(label)}</a></div>'
    )


def _served_url(path: Path) -> str | None:
    try:
        from jupyter_server.serverapp import list_running_servers
    except ImportError:
        return None
    parent = os.environ.get("JPY_PARENT_PID")
    for server in list_running_servers():
        if parent and str(server.get("pid")) != parent:
            continue
        root = server.get("root_dir")
        if not root or not path.resolve().is_relative_to(Path(root).resolve()):
            continue
        relative = path.resolve().relative_to(Path(root).resolve()).as_posix()
        return server.get("base_url", "/").rstrip("/") + "/files/" + quote(relative) + "?download=1"
    return None
