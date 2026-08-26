from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

import ipywidgets as widgets
import pytest
from _evaluation_diagnostic_fixtures import (
    FailingTransport as _FailingTransport,
)
from _evaluation_diagnostic_fixtures import (
    candidate as _candidate,
)
from _evaluation_diagnostic_fixtures import (
    load_benchmark as _load_benchmark,
)
from _evaluation_diagnostic_fixtures import (
    load_catalog as _load_catalog,
)
from _evaluation_diagnostic_fixtures import (
    load_details as _load_details,
)
from IPython.core.interactiveshell import InteractiveShell

import screamingface as sf
from screamingface._diagnostics.model import _new_receipt
from screamingface._diagnostics.store import _STORE
from screamingface._evaluation.runner import evaluate_sync
from screamingface._ui.diagnostic_view import (
    _STYLE,
    _attach_notebook_renderer,
    _display_notebook_diagnostic,
    _NotebookDiagnosticView,
)
from screamingface.diagnostic import DiagnosticReceipt


@pytest.fixture(autouse=True)
def _empty_diagnostics() -> Generator[None, None, None]:
    _STORE.clear()
    yield
    _STORE.clear()


def _receipt(*, outcome: str = "failed") -> DiagnosticReceipt:
    return _new_receipt(
        diagnostic_id="diag_example",
        session_id="session_example",
        occurred_at=datetime(2026, 8, 26, 17, 38, tzinfo=UTC),
        elapsed_seconds=1.25,
        operation="evaluate",
        outcome=outcome,
        client={"name": "screamingface-python", "host": "notebook"},
        error={"type": "TypeError"},
        context={"engine": {"host": "engine.example", "mode": "hosted"}},
        executions=[],
        breadcrumbs=[],
    )


def _walk(widget: widgets.Widget) -> tuple[widgets.Widget, ...]:
    children = getattr(widget, "children", ())
    return (widget, *(item for child in children for item in _walk(child)))


def _button(widget: widgets.Widget, description: str) -> widgets.Button:
    return next(
        item
        for item in _walk(widget)
        if isinstance(item, widgets.Button) and item.description == description
    )


def _html_values(widget: widgets.Widget) -> str:
    return "\n".join(item.value for item in _walk(widget) if isinstance(item, widgets.HTML))


def test_evaluation_attaches_one_renderer_to_the_original_raw_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = TypeError("benchmark is required")
    published: list[tuple[BaseException, DiagnosticReceipt]] = []
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        lambda raised, receipt: published.append((raised, receipt)),
    )

    with pytest.raises(TypeError) as caught:
        evaluate_sync(
            _load_benchmark,
            _FailingTransport(error),
            _load_catalog,
            _load_details,
            _candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is error
    renderer = getattr(error, "_render_traceback_")
    assert renderer() == []
    assert renderer() == []
    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert published == [(error, receipt)]


def test_renderer_attachment_failure_never_replaces_the_operation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = sf.ExecutionError("The Engine disconnected.")

    def broken_attachment(raised: BaseException, receipt: DiagnosticReceipt) -> None:
        del raised, receipt
        raise RuntimeError("notebook adapter failed")

    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._attach_notebook_renderer",
        broken_attachment,
    )

    with pytest.raises(sf.ExecutionError) as caught:
        evaluate_sync(
            _load_benchmark,
            _FailingTransport(error),
            _load_catalog,
            _load_details,
            _candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is error
    assert sf.diagnostics.last() is not None


def test_non_notebook_raw_exception_keeps_the_normal_traceback_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = TypeError("benchmark is required")
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: False,
    )

    _attach_notebook_renderer(error, _receipt())

    assert not hasattr(error, "_render_traceback_")


def test_notebook_renderer_falls_back_to_the_existing_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = sf.ExecutionError("The Engine disconnected.", code="websocket_disconnected")
    expected = error._render_traceback_()
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        lambda raised, receipt: (_ for _ in ()).throw(RuntimeError("display unavailable")),
    )

    _attach_notebook_renderer(error, _receipt())

    assert error._render_traceback_() == expected


def test_raw_exception_fallback_retains_its_python_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = TypeError("benchmark is required")
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        lambda raised, receipt: (_ for _ in ()).throw(RuntimeError("display unavailable")),
    )

    _attach_notebook_renderer(error, _receipt())

    rendered = "".join(getattr(error, "_render_traceback_")())
    assert "TypeError: benchmark is required" in rendered


def test_attaching_twice_keeps_the_first_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = TypeError("failed")
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )

    _attach_notebook_renderer(error, _receipt())
    first = getattr(error, "_render_traceback_")
    _attach_notebook_renderer(error, _receipt(outcome="cancelled"))

    assert getattr(error, "_render_traceback_") is first


def test_display_publishes_the_widget(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[widgets.Widget] = []
    monkeypatch.setattr("IPython.display.display", published.append)

    _display_notebook_diagnostic(TypeError("failed"), _receipt())

    assert len(published) == 1
    assert set(getattr(published[0], "_dom_classes", ())) >= {
        "sf-ui",
        "sf-diagnostic-widget",
    }


def test_ipython_invokes_the_attached_renderer_for_the_original_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = TypeError("failed")
    published: list[tuple[BaseException, DiagnosticReceipt]] = []
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        lambda raised, receipt: published.append((raised, receipt)),
    )
    receipt = _receipt()
    _attach_notebook_renderer(error, receipt)
    shell = InteractiveShell()
    shell.user_ns["diagnostic_test_error"] = error

    result = shell.run_cell("raise diagnostic_test_error")

    assert result.error_in_exec is error
    assert published == [(error, receipt)]


def test_panel_starts_concise_accessible_and_without_receipt_json() -> None:
    receipt = _receipt()
    view = _NotebookDiagnosticView(TypeError("benchmark is required"), receipt)

    html = _html_values(view.widget)
    assert "Evaluation failed" in html
    assert "benchmark is required" in html
    assert "diag_example" in html
    assert "Nothing has been sent" in html
    assert "%tb" in html
    assert receipt.to_json() not in unescape(html)
    assert "role='alert'" in html
    assert "aria-live='polite'" in html
    assert set(view.widget._dom_classes) >= {"sf-ui", "sf-diagnostic-widget"}
    # INVARIANT: container tooltips crash JupyterLab's VBoxView because VBox has no description.
    assert view.widget.tooltip is None
    assert _button(view.widget, "Export diagnostic").tooltip
    assert _button(view.widget, "Preview diagnostic").tooltip


@pytest.mark.parametrize(
    ("outcome", "title"),
    [
        ("interrupted_by_user", "Evaluation interrupted"),
        ("cancelled", "Evaluation cancelled"),
    ],
)
def test_panel_names_non_failure_terminal_outcomes(outcome: str, title: str) -> None:
    view = _NotebookDiagnosticView(KeyboardInterrupt(), _receipt(outcome=outcome))

    html = _html_values(view.widget)
    assert title in html
    assert "sf-diagnostic--stopped" in html


def test_panel_escapes_and_bounds_local_exception_text() -> None:
    private_markup = "<script>not markup</script>\n" + "x" * 600
    view = _NotebookDiagnosticView(TypeError(private_markup), _receipt())

    html = _html_values(view.widget)
    assert "<script>not markup</script>" not in html
    assert "&lt;script&gt;not markup&lt;/script&gt;" in html
    assert "x" * 501 not in html


def test_preview_reveals_the_exact_receipt_only_after_a_click() -> None:
    receipt = _receipt()
    view = _NotebookDiagnosticView(TypeError("failed"), receipt)

    preview = _button(view.widget, "Preview diagnostic")
    assert receipt.to_json() not in unescape(_html_values(view.widget))

    preview.click()

    assert receipt.to_json() in unescape(_html_values(view.widget))
    assert preview.description == "Hide diagnostic"
    preview.click()
    assert receipt.to_json() not in unescape(_html_values(view.widget))
    assert preview.description == "Preview diagnostic"


def test_export_writes_only_after_an_explicit_click(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    receipt = _receipt()
    view = _NotebookDiagnosticView(TypeError("failed"), receipt)
    selected = tmp_path / "screamingface-diagnostic.json"

    assert not selected.exists()
    _button(view.widget, "Export diagnostic").click()

    assert selected.read_text(encoding="utf-8") == receipt.to_json()
    assert "Exported screamingface-diagnostic.json" in _html_values(view.widget)


def test_export_failure_is_reported_inside_the_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_export(self: DiagnosticReceipt, path: object) -> Any:
        del self, path
        raise OSError("read-only filesystem")

    monkeypatch.setattr(DiagnosticReceipt, "export", unavailable_export)
    view = _NotebookDiagnosticView(TypeError("failed"), _receipt())

    _button(view.widget, "Export diagnostic").click()

    html = _html_values(view.widget)
    assert "Could not export the diagnostic" in html
    assert "read-only filesystem" not in html


def test_panel_uses_sfds_app_tokens_and_colab_theme_contract() -> None:
    assert "border-radius:0" in _STYLE
    assert "var(--sf-danger-solid)" in _STYLE
    assert "var(--sf-accent)" in _STYLE
    assert "background:var(--sf-gain)" not in _STYLE
    assert ':where(html[theme="light"]) .sf-ui' in _STYLE
    assert ':where(html[theme="dark"]) .sf-ui' in _STYLE
