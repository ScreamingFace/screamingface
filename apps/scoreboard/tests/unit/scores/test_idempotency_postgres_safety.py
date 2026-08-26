from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from tests.unit.scores.conftest import _with_schema


def test_postgres_regression_schema_url_isolated_from_the_configured_database() -> None:
    base = "postgres://user:pass@example.test/scoreboard?ssl=require"

    first = _with_schema(base, "scoreboard_idempotency_first")
    second = _with_schema(base, "scoreboard_idempotency_second")

    assert first != second
    assert dict(parse_qsl(urlsplit(first).query)) == {
        "ssl": "require",
        "schema": "scoreboard_idempotency_first",
    }
    assert dict(parse_qsl(urlsplit(second).query))["schema"] == "scoreboard_idempotency_second"
