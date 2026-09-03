"""Accessible notebook presentation for successful-operation client notices."""

from __future__ import annotations

from html import escape

from screamingface._notices import ClientNotice
from screamingface._ui.style import _theme_rules

_WARNING_LIGHT = (
    "--sf-notice-ink:#9c4828;--sf-notice-solid:#f1622d;"
    "--sf-notice-bg:#fdf4f1;--sf-notice-border:#d7aa9b"
)
_WARNING_DARK = (
    "--sf-notice-ink:#ffbca5;--sf-notice-solid:#e36f48;"
    "--sf-notice-bg:#130e0c;--sf-notice-border:#735248"
)
_INFO_LIGHT = (
    "--sf-notice-ink:#315f9b;--sf-notice-solid:#4b91f0;"
    "--sf-notice-bg:#f4f8fd;--sf-notice-border:#a9c6eb"
)
_INFO_DARK = (
    "--sf-notice-ink:#a9ccfa;--sf-notice-solid:#75affe;"
    "--sf-notice-bg:#0b1119;--sf-notice-border:#3d5c83"
)

_STYLE = f"""<style>
.sf-notice{{
  max-width:920px;display:grid;grid-template-columns:8px minmax(0,1fr);gap:10px;
  align-items:start;padding:10px 12px;color:var(--sf-notice-ink);
  background:var(--sf-notice-bg);border:1px solid var(--sf-notice-border);
  border-left:2px solid var(--sf-notice-solid);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px;line-height:1.45;
}}
.sf-notice--warning{{{_WARNING_LIGHT}}}
.sf-notice--info{{{_INFO_LIGHT}}}
{_theme_rules(".sf-notice--warning", _WARNING_LIGHT, _WARNING_DARK)}
{_theme_rules(".sf-notice--info", _INFO_LIGHT, _INFO_DARK)}
.sf-notice__mark{{width:8px;height:8px;margin-top:5px;background:var(--sf-notice-solid)}}
.sf-notice__title{{font-weight:600;line-height:1.35}}
.sf-notice__body{{line-height:1.45;margin-top:2px}}
</style>"""


def client_notice_html(notice: ClientNotice) -> str:
    """Render one self-contained notice with visible and machine-readable severity."""

    role = "alert" if notice.severity == "warning" else "status"
    return (
        f"{_STYLE}<div class='sf-notice sf-notice--{notice.severity}' role='{role}' "
        f"data-notice-code='{escape(notice.code, quote=True)}' "
        f"data-notice-severity='{notice.severity}'>"
        "<span class='sf-notice__mark' aria-hidden='true'></span>"
        f"<div><div class='sf-notice__title'>{escape(notice.title)}</div>"
        f"<div class='sf-notice__body'>{escape(notice.body)}</div></div></div>"
    )


def display_notebook_notice(notice: ClientNotice) -> None:
    """Publish one rich notice immediately, including when a cell assigns its result."""

    from IPython.display import HTML, display

    display(HTML(client_notice_html(notice)))


__all__ = ["client_notice_html", "display_notebook_notice"]
