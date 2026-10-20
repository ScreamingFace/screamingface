from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser

import screamingface as sf
from screamingface._ui.leaderboard_style import LEADERBOARD_STYLE
from screamingface._ui.leaderboard_view import leaderboard_catalog_html


def css_rules(css: str) -> dict[str, list[str]]:
    """Each selector mapped to its declaration blocks; an @media block keeps its inner selectors."""
    rules: dict[str, list[str]] = {}
    for chunk in css.split("}"):
        if "{" not in chunk:
            continue
        head, body = chunk.rsplit("{", 1)
        rules.setdefault(head.rsplit("{", 1)[-1].strip(), []).append(body.strip())
    return rules


class _RowSearchKeys(HTMLParser):
    """Collects the `data-sf-search` value of every catalogue row, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if "sf-lb-list__row" in (attributes.get("class") or "").split():
            self.rows.append(attributes.get("data-sf-search"))


def _info(leaderboard_id: str, display_name: str, description: str | None) -> sf.LeaderboardInfo:
    return sf.LeaderboardInfo(
        id=leaderboard_id,
        display_name=display_name,
        description=description,
        dataset_url=f"https://scoreboard.example/{leaderboard_id}.jsonl",
        created_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
    )


def _row_search_keys(values: list[sf.LeaderboardInfo]) -> list[str | None]:
    parser = _RowSearchKeys()
    parser.feed(leaderboard_catalog_html(values))
    return parser.rows


def test_a_hidden_catalogue_row_is_not_displayed() -> None:
    rules = css_rules(LEADERBOARD_STYLE)

    assert rules[".sf-lb-list__row[hidden]"] == ["display:none"]


def test_every_catalogue_row_carries_the_key_the_filter_reads() -> None:
    keys = _row_search_keys(
        [
            _info("draco", "DRACO", "Deep Research AI Comparison"),
            _info("ifeval", "IFEval", None),
        ]
    )

    assert keys == ["draco draco deep research ai comparison", "ifeval ifeval "]


def test_the_row_key_lowercases_like_the_filter_lowercases_the_query() -> None:
    keys = _row_search_keys([_info("strasse", "Straße", "Größe")])

    assert keys == ["strasse straße größe"]
