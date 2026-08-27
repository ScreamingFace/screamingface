"""Optional IPython presentation for retained local diagnostic receipts."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from html import escape
from typing import Any, cast

from screamingface._environment import running_in_notebook
from screamingface._ui.style import STYLE
from screamingface.diagnostic import DiagnosticReceipt

_EXPORT_PATH = "screamingface-diagnostic.json"

_STYLE = (
    STYLE
    + """<style>
.sf-diagnostic-widget{width:fit-content!important;max-width:100%!important;
  align-items:flex-start!important;gap:0!important;margin:0!important;
  border:0!important;box-shadow:none!important}
.sf-diagnostic__toolbar.widget-hbox{display:inline-flex!important;width:fit-content!important;
  max-width:100%!important;flex-flow:row wrap!important;
  align-items:center!important;justify-content:flex-start!important;gap:4px 12px!important;
  margin:0!important;padding:0!important;border:0!important;
  border-radius:0!important;background:transparent!important;color:var(--sf-ink)}
.sf-diagnostic__receipt{flex:0 1 auto!important;width:auto!important;min-width:0!important}
.sf-diagnostic__receipt>div>div{display:flex;flex-wrap:wrap;gap:4px;
  font:500 12px/1.4 var(--f-mono);color:var(--sf-ink-2)}
.sf-diagnostic__receipt code{font:inherit;color:var(--sf-ink)}
.sf-diagnostic__controls.widget-hbox{display:flex!important;flex-flow:row wrap!important;
  gap:4px!important;margin:0!important}
.sf-diagnostic-widget .widget-button{height:24px!important;width:auto!important;
  padding:0 4px!important;border:0!important;border-radius:0!important;box-shadow:none!important;
  background:transparent!important;background-image:none!important;color:var(--sf-accent)!important;
  text-decoration:underline;text-underline-offset:2px;
  font:600 12px/1 var(--f-mono)!important;white-space:nowrap}
.sf-diagnostic-widget .widget-button:hover{background:transparent!important;
  color:var(--sf-accent-hover)!important}
.sf-diagnostic__status{margin-top:4px;color:var(--sf-ink-2);
  font:500 12px/1.45 var(--f-mono)}
.sf-diagnostic__status:empty{display:none}
.sf-diagnostic__status--ok{color:var(--sf-success)}
.sf-diagnostic__status--bad{color:var(--sf-blind)}
.sf-diagnostic__preview{margin-top:8px;border:1px solid var(--sf-line-2);
  background:var(--sf-surface)}
.sf-diagnostic__preview-label{padding:8px 12px;border-bottom:1px solid var(--sf-line);
  font:600 11px/1.4 var(--f-mono);text-transform:uppercase;
  letter-spacing:.08em;color:var(--sf-ink-2)}
.sf-diagnostic__preview pre{max-height:280px;margin:0;padding:12px;overflow:auto;
  background:var(--sf-surface-2);color:var(--sf-ink);white-space:pre-wrap;overflow-wrap:anywhere;
  font:500 12px/1.5 var(--f-mono)}
@media(max-width:560px){.sf-diagnostic__receipt{flex-basis:100%!important}}
</style>"""
)


class _NotebookDiagnosticView:
    """One local diagnostic panel; actions never leave the kernel."""

    def __init__(self, receipt: DiagnosticReceipt) -> None:
        import ipywidgets as widgets

        self._receipt = receipt
        self._preview_visible = False
        self._receipt_html: Any = widgets.HTML(value=f"{_STYLE}{_receipt_html(receipt)}")
        self._receipt_html.add_class("sf-diagnostic__receipt")
        self._export: Any = widgets.Button(
            description="Export",
            tooltip="Save this diagnostic as a local JSON file",
        )
        self._export.on_click(self._export_receipt)
        self._preview_button: Any = widgets.Button(
            description="Preview",
            tooltip="Show the exact diagnostic JSON held in this kernel",
        )
        self._preview_button.on_click(self._toggle_preview)
        self._controls: Any = widgets.HBox(children=(self._export, self._preview_button))
        self._controls.add_class("sf-diagnostic__controls")
        self._toolbar: Any = widgets.HBox(children=(self._receipt_html, self._controls))
        self._toolbar.add_class("sf-diagnostic__toolbar")
        self._status: Any = widgets.HTML(value=_status_html())
        self._preview: Any = widgets.HTML(value="")
        # INVARIANT: VBox has no description; a truthy tooltip crashes JupyterLab's VBoxView.
        self.widget: Any = widgets.VBox(
            children=(self._toolbar, self._status, self._preview),
        )
        self.widget.add_class("sf-ui")
        self.widget.add_class("sf-diagnostic-widget")

    def _toggle_preview(self, _: object) -> None:
        self._preview_visible = not self._preview_visible
        if self._preview_visible:
            self._preview.value = _preview_html(self._receipt)
            self._preview_button.description = "Hide"
            self._preview_button.tooltip = "Hide the diagnostic JSON preview"
        else:
            self._preview.value = ""
            self._preview_button.description = "Preview"
            self._preview_button.tooltip = "Show the exact diagnostic JSON held in this kernel"

    def _export_receipt(self, _: object) -> None:
        try:
            selected = self._receipt.export(_EXPORT_PATH)
        except (OSError, ValueError):
            self._status.value = _status_html(
                "Could not export the diagnostic. Choose a writable working directory and retry.",
                state="bad",
            )
            return
        self._status.value = _status_html(f"Exported {selected.name}", state="ok")


def _attach_notebook_renderer(error: BaseException, receipt: DiagnosticReceipt) -> None:
    """Attach one IPython renderer without changing the exception contract."""

    if not running_in_notebook():
        return
    if getattr(error, "_screamingface_diagnostic_id", None) is not None:
        return
    fallback = _fallback_renderer(error)
    shown = False

    def render() -> list[str]:
        nonlocal shown
        if shown:
            return []
        try:
            _display_notebook_diagnostic(receipt)
        except Exception:
            # INVARIANT: optional presentation can never hide the operation's real traceback.
            return fallback()
        shown = True
        return []

    # WHY: IPython asks the exception value for this protocol. An instance attachment also covers
    # raw TypeError/ValueError failures without wrapping them or intercepting unrelated cells.
    setattr(error, "_screamingface_diagnostic_id", receipt.diagnostic_id)
    setattr(error, "_render_traceback_", render)


def _fallback_renderer(error: BaseException) -> Callable[[], list[str]]:
    existing = getattr(error, "_render_traceback_", None)
    if callable(existing):
        return cast(Callable[[], list[str]], existing)

    def render() -> list[str]:
        return traceback.format_exception(type(error), error, error.__traceback__)

    return render


def _display_notebook_diagnostic(
    receipt: DiagnosticReceipt,
) -> None:
    from IPython.display import display

    display(_NotebookDiagnosticView(receipt).widget)


def _receipt_html(receipt: DiagnosticReceipt) -> str:
    diagnostic_id = escape(receipt.diagnostic_id, quote=True)
    visible_id = escape(_visible_diagnostic_id(receipt.diagnostic_id))
    return (
        "<div role='group' aria-label='ScreamingFace diagnostic receipt'>"
        f"<code title='{diagnostic_id}' aria-label='Diagnostic ID {diagnostic_id}'>"
        f"{visible_id}</code>"
        "<span>·</span><span aria-label='Local only; cleared when this kernel restarts'>"
        "local only</span><span>·</span>"
        "<code title='Inspect the original traceback'>%tb</code>"
        "</div>"
    )


def _visible_diagnostic_id(diagnostic_id: str) -> str:
    if len(diagnostic_id) <= 14:
        return diagnostic_id
    return f"{diagnostic_id[:9]}…{diagnostic_id[-4:]}"


def _status_html(message: str = "", *, state: str | None = None) -> str:
    state_class = "" if state is None else f" sf-diagnostic__status--{state}"
    return (
        f"<div class='sf-diagnostic__status{state_class}' role='status' "
        f"aria-live='polite'>{escape(message)}</div>"
    )


def _preview_html(receipt: DiagnosticReceipt) -> str:
    return (
        "<div class='sf-diagnostic__preview'>"
        "<div class='sf-diagnostic__preview-label'>Receipt JSON</div>"
        f"<pre tabindex='0' aria-label='Diagnostic JSON'>{escape(receipt.to_json())}</pre></div>"
    )


__all__: list[str] = []
