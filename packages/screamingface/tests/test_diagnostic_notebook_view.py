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
from screamingface._diagnostics.model import _new_receipt, _ReceiptEvidence
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


def _receipt(
    *,
    diagnostic_id: str = "diag_example",
    outcome: str = "failed",
) -> DiagnosticReceipt:
    return _new_receipt(
        _ReceiptEvidence(
            diagnostic_id=diagnostic_id,
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
    published: list[DiagnosticReceipt] = []
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._diagnostics.evaluation.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        published.append,
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
    assert not getattr(error, "__notes__", ())
    renderer = getattr(error, "_render_traceback_")
    first = renderer()
    second = renderer()
    assert "TypeError: benchmark is required" in "".join(first)
    assert second == first
    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert published == [receipt]


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
    receipt = _receipt()
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        lambda receipt: (_ for _ in ()).throw(RuntimeError("display unavailable")),
    )

    _attach_notebook_renderer(error, receipt)

    rendered = error._render_traceback_()
    assert rendered[: len(expected)] == expected
    recovery = "".join(rendered[len(expected) :])
    assert recovery.count(receipt.diagnostic_id) == 2
    assert (
        f'sf.diagnostics.get("{receipt.diagnostic_id}").export("screamingface-diagnostic.json")'
    ) in recovery


def test_failed_notebook_display_is_logged_without_receipt_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = TypeError("benchmark is required")
    receipt = _receipt(diagnostic_id="diag_private_evidence")
    attempts = 0

    def fail_display(selected: DiagnosticReceipt) -> None:
        nonlocal attempts
        assert selected is receipt
        attempts += 1
        raise RuntimeError("display unavailable")

    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        fail_display,
    )

    _attach_notebook_renderer(error, receipt)

    first = getattr(error, "_render_traceback_")()
    second = getattr(error, "_render_traceback_")()
    assert second == first
    assert attempts == 1
    assert "".join(first).count("Diagnostic: ") == 1
    assert (
        len(
            [
                record
                for record in caplog.records
                if record.message == "ScreamingFace diagnostic presentation failed"
            ]
        )
        == 1
    )
    assert receipt.to_json() not in caplog.text


def test_notebook_renderer_preserves_existing_traceback_after_successful_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = sf.ExecutionError("The Engine disconnected.", code="websocket_disconnected")
    expected = error._render_traceback_()
    published: list[DiagnosticReceipt] = []
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        published.append,
    )
    receipt = _receipt()

    _attach_notebook_renderer(error, receipt)

    assert error._render_traceback_() == expected
    assert error._render_traceback_() == expected
    assert published == [receipt]


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
        lambda receipt: (_ for _ in ()).throw(RuntimeError("display unavailable")),
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

    _display_notebook_diagnostic(_receipt())

    assert len(published) == 1
    assert set(getattr(published[0], "_dom_classes", ())) >= {
        "sf-ui",
        "sf-diagnostic-widget",
    }


def test_ipython_invokes_the_attached_renderer_for_the_original_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = TypeError("failed")
    published: list[DiagnosticReceipt] = []
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view.running_in_notebook",
        lambda: True,
    )
    monkeypatch.setattr(
        "screamingface._ui.diagnostic_view._display_notebook_diagnostic",
        published.append,
    )
    receipt = _receipt()
    _attach_notebook_renderer(error, receipt)
    shell = InteractiveShell()
    shell.user_ns["diagnostic_test_error"] = error

    result = shell.run_cell("raise diagnostic_test_error")

    assert result.error_in_exec is error
    assert published == [receipt]


def test_panel_starts_concise_accessible_and_without_receipt_json() -> None:
    receipt = _receipt()
    view = _NotebookDiagnosticView(receipt)

    html = _html_values(view.widget)
    assert "Evaluation failed" not in html
    assert "benchmark is required" not in html
    assert "Diagnostic" in html
    assert "diag_example" in html
    assert "local only" not in html
    assert "%tb" not in html
    assert "Stored in this runtime" not in html
    assert "sf-diagnostic__eyebrow" not in html
    assert "Nothing has been sent" not in html
    assert "Run <code>%tb</code>" not in html
    assert receipt.to_json() not in unescape(html)
    assert "role='alert'" not in html
    assert "aria-live='polite'" in html
    assert set(view.widget._dom_classes) >= {"sf-ui", "sf-diagnostic-widget"}
    # INVARIANT: container tooltips crash JupyterLab's VBoxView because VBox has no description.
    assert view.widget.tooltip is None
    assert _button(view.widget, "Save JSON").tooltip
    assert _button(view.widget, "View details").tooltip
    assert tuple(button.description for button in view._controls.children) == (
        "View details",
        "Save JSON",
    )
    assert view._status.layout.display == "none"
    assert view._preview.layout.display == "none"
    assert any(
        "sf-diagnostic__toolbar" in getattr(item, "_dom_classes", ()) for item in _walk(view.widget)
    )


@pytest.mark.parametrize(
    ("outcome", "title"),
    [
        ("interrupted_by_user", "Evaluation interrupted"),
        ("cancelled", "Evaluation cancelled"),
    ],
)
def test_toolbar_does_not_restate_terminal_outcomes(outcome: str, title: str) -> None:
    view = _NotebookDiagnosticView(_receipt(outcome=outcome))

    html = _html_values(view.widget)
    assert title not in html
    assert "sf-diagnostic--stopped" not in html


def test_toolbar_does_not_duplicate_local_exception_text() -> None:
    private_markup = "<script>not markup</script>\n" + "x" * 600
    view = _NotebookDiagnosticView(_receipt())

    html = _html_values(view.widget)
    assert private_markup not in html
    assert "&lt;script&gt;not markup&lt;/script&gt;" not in html


def test_toolbar_shortens_only_the_visible_diagnostic_id() -> None:
    diagnostic_id = "diag_1234567890abcdef"
    view = _NotebookDiagnosticView(_receipt(diagnostic_id=diagnostic_id))

    html = _html_values(view.widget)
    assert "diag_1234…cdef" in html
    assert f"title='{diagnostic_id}'" in html
    assert f"aria-label='Diagnostic ID {diagnostic_id}'" in html


def test_view_details_reveals_the_exact_receipt_and_recovery_guidance() -> None:
    receipt = _receipt()
    view = _NotebookDiagnosticView(receipt)

    details = _button(view.widget, "View details")
    assert receipt.to_json() not in unescape(_html_values(view.widget))

    details.click()

    html = unescape(_html_values(view.widget))
    assert receipt.to_json() in html
    assert "Stored in this runtime until restart" in html
    assert "Run <code>%tb</code>" in html
    assert details.description == "Hide details"
    assert view._preview.layout.display == "block"
    details.click()
    assert receipt.to_json() not in unescape(_html_values(view.widget))
    assert details.description == "View details"
    assert view._preview.layout.display == "none"


def test_save_json_writes_only_after_an_explicit_click(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    receipt = _receipt()
    view = _NotebookDiagnosticView(receipt)
    selected = tmp_path / "screamingface-diagnostic.json"

    assert not selected.exists()
    assert view._status.layout.display == "none"
    _button(view.widget, "Save JSON").click()

    assert selected.read_text(encoding="utf-8") == receipt.to_json()
    assert "Saved to screamingface-diagnostic.json" in _html_values(view.widget)
    assert view._status.layout.display == "block"


def test_save_json_failure_is_reported_inside_the_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_export(self: DiagnosticReceipt, path: object) -> Any:
        del self, path
        raise OSError("read-only filesystem")

    monkeypatch.setattr(DiagnosticReceipt, "export", unavailable_export)
    view = _NotebookDiagnosticView(_receipt())

    _button(view.widget, "Save JSON").click()

    html = _html_values(view.widget)
    assert "Could not save the diagnostic" in html
    assert "read-only filesystem" not in html
    assert view._status.layout.display == "block"


def test_panel_uses_sfds_app_tokens_and_colab_theme_contract() -> None:
    assert "border-radius:0" in _STYLE
    assert "var(--sf-danger-solid)" in _STYLE
    assert "var(--sf-blind)" not in _STYLE.split("<style>")[-1]
    assert "var(--sf-accent)" in _STYLE
    assert "background:var(--sf-gain)" not in _STYLE
    assert ".sf-diagnostic__toolbar.widget-hbox" in _STYLE
    assert ".sf-diagnostic__receipt>div>div" in _STYLE
    assert "height:24px!important" in _STYLE
    assert "text-decoration:underline" in _STYLE
    assert "width:fit-content!important" in _STYLE
    assert "justify-content:flex-start!important" in _STYLE
    assert ".sf-diagnostic__receipt{flex:0 1 auto!important" in _STYLE
    assert ':where(html[theme="light"]) .sf-ui' in _STYLE
    assert ':where(html[theme="dark"]) .sf-ui' in _STYLE


def test_receipt_toolbar_is_unboxed_supporting_evidence() -> None:
    root_rule = _STYLE.split(".sf-diagnostic-widget", 1)[1].split("}", 1)[0]
    toolbar_rule = _STYLE.split(".sf-diagnostic__toolbar.widget-hbox", 1)[1].split("}", 1)[0]

    assert "background:transparent!important" in root_rule
    assert "border:0!important" in toolbar_rule
    assert "background:transparent!important" in toolbar_rule
    assert "padding:0!important" in toolbar_rule


def test_diagnostic_style_uses_sfds_font_and_spacing_tokens() -> None:
    diagnostic_rules = _STYLE.split("<style>")[-1]

    assert "var(--f-mono)" in diagnostic_rules
    assert '"IBM Plex Mono"' not in diagnostic_rules
    assert "gap:6px" not in diagnostic_rules
    assert "padding:0 3px" not in diagnostic_rules
    assert "padding:10px" not in diagnostic_rules


def test_colab_root_does_not_shrink_wrap_the_content_hugging_toolbar() -> None:
    root_rule = _STYLE.split(".sf-diagnostic-widget", 1)[1].split("}", 1)[0]
    toolbar_rule = _STYLE.split(".sf-diagnostic__toolbar.widget-hbox", 1)[1].split("}", 1)[0]

    # INVARIANT: Colab collapses nested fit-content flex containers even though their children
    # render independently. Only the visible toolbar should hug its content.
    assert "width:fit-content" not in root_rule
    assert "width:fit-content" in toolbar_rule
