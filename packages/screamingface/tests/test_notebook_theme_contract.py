from __future__ import annotations

import pytest

from screamingface._ui.connection_view import _STYLE as CONNECTION_STYLE
from screamingface._ui.leaderboard_style import LEADERBOARD_STYLE
from screamingface._ui.notice_view import _STYLE as NOTICE_STYLE
from screamingface._ui.style import STYLE


@pytest.mark.parametrize(
    ("css", "selector"),
    [
        (STYLE, ".sf-ui"),
        (LEADERBOARD_STYLE, ".sf-lb"),
        (NOTICE_STYLE, ".sf-notice--warning"),
        (NOTICE_STYLE, ".sf-notice--info"),
        (CONNECTION_STYLE, ".sf-tile-icon--logo .sf-icon-light"),
        (CONNECTION_STYLE, ".sf-tile-icon--logo .sf-icon-dark"),
    ],
)
def test_every_notebook_theme_block_honours_colab(
    css: str,
    selector: str,
) -> None:
    assert f':where(html[theme="light"]) {selector}' in css
    assert f':where(html[theme="dark"]) {selector}' in css


def test_nested_widgets_take_text_colour_from_the_panel_not_the_host() -> None:
    # WHY: ipywidgets paints every nested widget `color:var(--jp-widgets-color)`; VS Code
    # defines no JupyterLab theme, so that resolves to black — black text on the dark panel.
    assert ".sf-ui .widget-box,.sf-ui .widget-html{color:inherit}" in STYLE


def test_vscode_white_widget_frame_is_dropped_only_around_a_panel() -> None:
    # WHY: VS Code paints every widget output `#fff !important`, a white band around a dark
    # panel; scoped with :has so other libraries' widgets keep the host's frame.
    frame_rule = ".cell-output-ipywidget-background:has(.sf-ui){background:transparent!important}"
    assert frame_rule in STYLE
