"""Optional IPython presentation for retained local diagnostic receipts."""

from __future__ import annotations

import traceback
import unicodedata
from collections.abc import Callable, Mapping
from html import escape
from typing import Any, cast

from screamingface._environment import running_in_notebook
from screamingface._ui.style import STYLE
from screamingface.diagnostic import DiagnosticReceipt

_EXPORT_PATH = "screamingface-diagnostic.json"

_STYLE = (
    STYLE
    + """<style>
.sf-diagnostic-widget.widget-vbox{width:100%!important;max-width:920px!important;
  margin:0!important;border:0!important;box-shadow:none!important}
.sf-diagnostic__panel{--sf-diagnostic-solid:var(--sf-danger-solid);
  --sf-diagnostic-bg:var(--sf-blind-bg);--sf-diagnostic-text:var(--sf-blind);
  display:grid;grid-template-columns:10px minmax(0,1fr);gap:12px;padding:14px 16px;
  border:1px solid var(--sf-line-2);border-left:2px solid var(--sf-diagnostic-solid);
  border-radius:0;background:var(--sf-diagnostic-bg);color:var(--sf-ink)}
.sf-diagnostic__panel.sf-diagnostic--stopped{--sf-diagnostic-solid:var(--sf-warning-solid);
  --sf-diagnostic-bg:var(--sf-warning-bg);--sf-diagnostic-text:var(--sf-warning)}
.sf-diagnostic__mark{width:10px;height:10px;margin-top:5px;background:var(--sf-diagnostic-solid)}
.sf-diagnostic__eyebrow{font:600 11px/1.4 "IBM Plex Mono",ui-monospace,monospace;
  text-transform:uppercase;letter-spacing:.08em;color:var(--sf-diagnostic-text)}
.sf-diagnostic__title{margin-top:4px;font-size:20px;font-weight:600;line-height:1.25}
.sf-diagnostic__message{margin-top:5px;font-size:14px;line-height:1.45;white-space:pre-wrap}
.sf-diagnostic__receipt{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;
  font:500 12px/1.45 "IBM Plex Mono",ui-monospace,monospace;color:var(--sf-ink-2)}
.sf-diagnostic__receipt code,.sf-diagnostic__trace code{font:inherit;color:var(--sf-ink)}
.sf-diagnostic__meta,.sf-diagnostic__trace{margin-top:5px;color:var(--sf-ink-2);
  font-size:12px;line-height:1.45}
.sf-diagnostic__controls.widget-hbox{display:flex!important;flex-flow:row wrap!important;
  gap:6px!important;margin:10px 0 0!important}
.sf-diagnostic-widget .widget-button{height:32px!important;width:auto!important;
  padding:0 12px!important;
  border:1px solid var(--sf-line-2)!important;border-radius:0!important;box-shadow:none!important;
  background:transparent!important;background-image:none!important;color:var(--sf-ink-2)!important;
  font:600 13px/1 "IBM Plex Mono",ui-monospace,monospace!important;white-space:nowrap}
.sf-diagnostic-widget .widget-button:hover{background:var(--sf-surface)!important;
  border-color:var(--sf-ink-2)!important;color:var(--sf-ink)!important}
.sf-diagnostic-widget .sf-diagnostic__export{background:var(--sf-accent)!important;
  border-color:var(--sf-accent)!important;color:var(--sf-accent-contrast)!important}
.sf-diagnostic-widget .sf-diagnostic__export:hover{background:var(--sf-accent-hover)!important;
  border-color:var(--sf-accent-hover)!important;color:var(--sf-accent-contrast)!important}
.sf-diagnostic__status{min-height:18px;margin-top:6px;color:var(--sf-ink-2);
  font:500 12px/1.45 "IBM Plex Mono",ui-monospace,monospace}
.sf-diagnostic__status--ok{color:var(--sf-success)}
.sf-diagnostic__status--bad{color:var(--sf-blind)}
.sf-diagnostic__preview{margin-top:8px;border:1px solid var(--sf-line-2);
  background:var(--sf-surface)}
.sf-diagnostic__preview-label{padding:8px 10px;border-bottom:1px solid var(--sf-line);
  font:600 11px/1.4 "IBM Plex Mono",ui-monospace,monospace;text-transform:uppercase;
  letter-spacing:.08em;color:var(--sf-ink-2)}
.sf-diagnostic__preview pre{max-height:280px;margin:0;padding:10px;overflow:auto;
  background:var(--sf-surface-2);color:var(--sf-ink);white-space:pre-wrap;overflow-wrap:anywhere;
  font:500 12px/1.5 "IBM Plex Mono",ui-monospace,monospace}
@media(max-width:560px){.sf-diagnostic__panel{padding:12px}.sf-diagnostic__controls.widget-hbox{
  flex-direction:column!important;align-items:stretch!important}
  .sf-diagnostic-widget .widget-button{
  width:100%!important}}
</style>"""
)


class _NotebookDiagnosticView:
    """One local diagnostic panel; actions never leave the kernel."""

    def __init__(self, error: BaseException, receipt: DiagnosticReceipt) -> None:
        import ipywidgets as widgets

        self._receipt = receipt
        self._preview_visible = False
        self._summary: Any = widgets.HTML(value=f"{_STYLE}{_summary_html(error, receipt)}")
        self._export: Any = widgets.Button(
            description="Export diagnostic",
            tooltip="Save this diagnostic as a local JSON file",
        )
        self._export.add_class("sf-diagnostic__export")
        self._export.on_click(self._export_receipt)
        self._preview_button: Any = widgets.Button(
            description="Preview diagnostic",
            tooltip="Show the exact diagnostic JSON held in this kernel",
        )
        self._preview_button.on_click(self._toggle_preview)
        self._controls: Any = widgets.HBox(children=(self._export, self._preview_button))
        self._controls.add_class("sf-diagnostic__controls")
        self._status: Any = widgets.HTML(value=_status_html())
        self._preview: Any = widgets.HTML(value="")
        self.widget: Any = widgets.VBox(
            children=(self._summary, self._controls, self._status, self._preview),
            tooltip="ScreamingFace diagnostic",
        )
        self.widget.add_class("sf-ui")
        self.widget.add_class("sf-diagnostic-widget")

    def _toggle_preview(self, _: object) -> None:
        self._preview_visible = not self._preview_visible
        if self._preview_visible:
            self._preview.value = _preview_html(self._receipt)
            self._preview_button.description = "Hide diagnostic"
            self._preview_button.tooltip = "Hide the diagnostic JSON preview"
        else:
            self._preview.value = ""
            self._preview_button.description = "Preview diagnostic"
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
            _display_notebook_diagnostic(error, receipt)
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
    error: BaseException,
    receipt: DiagnosticReceipt,
) -> None:
    from IPython.display import display

    display(_NotebookDiagnosticView(error, receipt).widget)


def _summary_html(error: BaseException, receipt: DiagnosticReceipt) -> str:
    stopped = receipt.outcome in {"interrupted_by_user", "cancelled"}
    state_class = " sf-diagnostic--stopped" if stopped else ""
    title = _outcome_title(receipt.outcome)
    message = _local_message(error)
    error_document = receipt.to_dict().get("error")
    code = error_document.get("code") if isinstance(error_document, Mapping) else None
    identity = (
        type(error).__name__ if not isinstance(code, str) else f"{type(error).__name__} · {code}"
    )
    title_id = f"sf-diagnostic-title-{receipt.diagnostic_id}"
    return (
        f"<div class='sf-diagnostic__panel{state_class}' role='alert' "
        f"aria-labelledby='{escape(title_id, quote=True)}'>"
        "<span class='sf-diagnostic__mark' aria-hidden='true'></span><div>"
        "<div class='sf-diagnostic__eyebrow'>Diagnostic</div>"
        f"<div class='sf-diagnostic__title' id='{escape(title_id, quote=True)}'>"
        f"{escape(title)}</div>"
        f"<div class='sf-diagnostic__message'>{escape(message)}</div>"
        f"<div class='sf-diagnostic__receipt'><span>{escape(identity)}</span>"
        f"<span>·</span><code>{escape(receipt.diagnostic_id)}</code></div>"
        "<div class='sf-diagnostic__meta'>Nothing has been sent. This receipt is held only in "
        "this kernel; restarting discards it.</div>"
        "<div class='sf-diagnostic__trace'>Run <code>%tb</code> to inspect the original "
        "traceback.</div></div></div>"
    )


def _outcome_title(outcome: str) -> str:
    if outcome == "interrupted_by_user":
        return "Evaluation interrupted"
    if outcome == "cancelled":
        return "Evaluation cancelled"
    return "Evaluation failed"


def _local_message(error: BaseException) -> str:
    value = str(error).strip() or type(error).__name__
    inert = "".join(
        " " if unicodedata.category(character).startswith("C") else character for character in value
    )
    return " ".join(inert.split())[:500]


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
