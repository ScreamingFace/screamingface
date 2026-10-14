from __future__ import annotations

from datetime import UTC, datetime

import screamingface as sf
from screamingface._ui.leaderboard_view import leaderboard_catalog_html


def test_catalog_filter_hides_rows_it_marks_hidden() -> None:
    html = leaderboard_catalog_html(
        [
            sf.LeaderboardInfo(
                id="draco",
                display_name="DRACO",
                description="Deep Research AI Comparison",
                dataset_url="https://scoreboard.example/draco.jsonl",
                created_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
            )
        ]
    )

    assert "row.hidden=" in html
    assert ".sf-lb-list__row[hidden]{display:none}" in html
