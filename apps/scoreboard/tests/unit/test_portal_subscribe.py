"""The email subscribe forms ship on every public portal page.

Every page carries the site-wide form's mount point and loads subscribe.js; the per-board form is
rendered by subscribe.js on a board page, so it needs no markup of its own. The forms post to a
public HubSpot endpoint whose ids are public by design — the portal holds no secret for them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from scoreboard.config import Settings
from scoreboard.main import create_app

_PAGES = ("/index.html", "/benchmark.html", "/spec.html", "/data.html", "/about.html")


def _settings(tmp_path: Path) -> Settings:
    values: dict[str, Any] = {
        "database_url": f"sqlite://{tmp_path / 'scoreboard.sqlite3'}",
        "cors_origins": [],
    }
    return Settings(**values)


def test_every_page_carries_the_site_wide_subscribe_form(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        for path in _PAGES:
            text = client.get(path).text
            assert 'data-subscribe="all"' in text, path
            assert '<script src="subscribe.js" defer></script>' in text, path


def test_subscribe_script_is_served(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/subscribe.js")
        assert response.status_code == 200
        assert "api.hsforms.com/submissions/v3/integration/submit/" in response.text
