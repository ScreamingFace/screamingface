"""Executed notebook -> HTML, shown only inside an empty-sandbox iframe (untrusted outputs).

The notebook may come from an unzipped CI artifact, so it is untrusted twice over: its
outputs may carry hostile markup (contained by ``sandboxed_iframe``: ``sandbox=""`` means no
scripts, no same-origin, no forms, no top navigation), and the file itself may be oversized
or malformed (``notebook_html`` then returns a small marker document instead of raising, so
the bundle page still renders).
"""

from __future__ import annotations

import html
from pathlib import Path

import nbformat
from nbconvert import HTMLExporter

NOTEBOOK_CAP_BYTES = 32 << 20  # an executed notebook with inline images stays well below
UNREADABLE_NOTEBOOK = "[notebook unreadable]"


def _marker(reason: str) -> str:
    return (
        "<!DOCTYPE html><html><body><p>"
        f"{html.escape(UNREADABLE_NOTEBOOK)} {html.escape(reason)}"
        "</p></body></html>"
    )


class _Unreadable(Exception):
    """The notebook file cannot be shown; the message is the human reason."""


def _read_capped(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            raw = fh.read(NOTEBOOK_CAP_BYTES + 1)
    except OSError as exc:
        raise _Unreadable(f"cannot read: {type(exc).__name__}") from exc
    if len(raw) > NOTEBOOK_CAP_BYTES:
        raise _Unreadable(f"too large (over {NOTEBOOK_CAP_BYTES} bytes)")
    return raw.decode("utf-8", errors="replace")


def _convert(text: str) -> str:
    try:
        nb = nbformat.reads(text, as_version=4)
        nbformat.validate(nb)
        nb.metadata.pop("widgets", None)  # widget state cannot render outside a kernel
        exporter = HTMLExporter(template_name="classic")
        exporter.exclude_input_prompt = True
        exporter.exclude_output_prompt = True
        body, _ = exporter.from_notebook_node(nb)
    except Exception as exc:  # noqa: BLE001 — any parse/convert failure degrades, never 500s
        raise _Unreadable(f"invalid notebook: {type(exc).__name__}") from exc
    return body


def notebook_html(path: Path) -> str:
    """Full HTML document for the executed notebook at ``path`` (or a marker document)."""
    try:
        return _convert(_read_capped(path))
    except _Unreadable as exc:
        return _marker(str(exc))


def sandboxed_iframe(document: str) -> str:
    """Embed ``document`` as inert ``srcdoc`` text of an iframe with an empty sandbox."""
    return (
        '<iframe class="nb" sandbox="" referrerpolicy="no-referrer" '
        f'srcdoc="{html.escape(document, quote=True)}"></iframe>'
    )
