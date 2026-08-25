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
