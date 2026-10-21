"""Workbench UI notebook rendering (unit 4 plan, Task 3): untrusted outputs stay sandboxed."""

from __future__ import annotations

from pathlib import Path

import nbformat

from workbench.ui.render import (
    NOTEBOOK_CAP_BYTES,
    UNREADABLE_NOTEBOOK,
    notebook_html,
    sandboxed_iframe,
)

HOSTILE = (
    '<script>alert(1)</script><img src="x" onerror="alert(2)"><a href="javascript:alert(3)">y</a>'
)


def _nb(tmp_path: Path, html_output: str) -> Path:
    cell = nbformat.v4.new_code_cell("x")
    cell.outputs = [nbformat.v4.new_output("display_data", data={"text/html": html_output})]
    nb = nbformat.v4.new_notebook(cells=[cell])
    nb.metadata["widgets"] = {"application/vnd.jupyter.widget-state+json": {"state": {}}}
    path = tmp_path / "executed.ipynb"
    nbformat.write(nb, path)
    return path


def test_notebook_renders_to_a_full_document(tmp_path: Path) -> None:
    doc = notebook_html(_nb(tmp_path, "<b>score 0.9</b>"))
    assert "<html" in doc.lower() and "score 0.9" in doc


def test_notebook_drops_widget_state(tmp_path: Path) -> None:
    doc = notebook_html(_nb(tmp_path, "<b>ok</b>"))
    assert "widget-state+json" not in doc


def test_iframe_has_an_empty_sandbox_and_escaped_srcdoc() -> None:
    frame = sandboxed_iframe('<script>alert(1)</script><a href="javascript:x">y</a>')
    assert 'sandbox=""' in frame
    assert 'referrerpolicy="no-referrer"' in frame
    assert "<script>" not in frame  # escaped into the attribute
    assert "&lt;script&gt;" in frame


def test_hostile_output_never_reaches_the_ui_origin_as_markup(tmp_path: Path) -> None:
    frame = sandboxed_iframe(notebook_html(_nb(tmp_path, HOSTILE)))
    # The only markup in the UI page is the iframe element itself; everything the
    # notebook carries (its own template scripts included) is inert srcdoc text.
    assert frame.count("<") == 2 and frame.startswith("<iframe ") and frame.endswith("</iframe>")
    assert frame.count('"') == 2 * frame.count('="')  # no attribute breakout via quotes
    assert "&lt;script&gt;alert(1)" in frame


def test_malformed_notebook_degrades_to_a_marker_document(tmp_path: Path) -> None:
    path = tmp_path / "executed.ipynb"
    path.write_text("{not json")
    doc = notebook_html(path)
    assert UNREADABLE_NOTEBOOK in doc and "<html" in doc.lower()


def test_wrong_shape_notebook_degrades_to_a_marker_document(tmp_path: Path) -> None:
    path = tmp_path / "executed.ipynb"
    path.write_text('{"cells": "nope"}')
    assert UNREADABLE_NOTEBOOK in notebook_html(path)


def test_missing_notebook_degrades_to_a_marker_document(tmp_path: Path) -> None:
    assert UNREADABLE_NOTEBOOK in notebook_html(tmp_path / "gone.ipynb")


def test_oversized_notebook_is_not_rendered(tmp_path: Path) -> None:
    path = tmp_path / "executed.ipynb"
    with path.open("wb") as fh:
        fh.truncate(NOTEBOOK_CAP_BYTES + 1)  # sparse; never parsed
    doc = notebook_html(path)
    assert UNREADABLE_NOTEBOOK in doc and "too large" in doc
