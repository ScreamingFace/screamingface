from __future__ import annotations

from importlib import import_module
from urllib.parse import parse_qsl, urlsplit

from tests.unit.scores.conftest import POSTGRES_IDEMPOTENCY_TEST, _with_schema


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


def test_the_isolation_fixture_still_covers_every_postgres_test() -> None:
    # INVARIANT: `_isolate_postgres_idempotency_regression` keys off a hardcoded test NAME, and
    # the test it guards keeps an unfiltered `IdempotencyKey.all()` assertion and an unfiltered
    # `.delete()` cleanup. Two edits silently unguard that cleanup against the CONFIGURED
    # database: renaming the test (the fixture stops matching and yields), or adding a second
    # PostgreSQL test in the same style (never matched in the first place).
    #
    # Both failures are SILENT — the suite stays green while wiping a shared table, which is the
    # exact finding this fixture exists to answer (review round 4 of PR #719). This assertion is
    # what turns either edit red. Adding a test here is fine; update the fixture to cover it and
    # extend this expectation deliberately.
    module = import_module("tests.unit.scores.test_idempotency_postgres")
    defined_tests = sorted(
        name
        for name, value in vars(module).items()
        if name.startswith("test_")
        and callable(value)
        and getattr(value, "__module__", None) == module.__name__
    )

    assert defined_tests == [POSTGRES_IDEMPOTENCY_TEST], (
        "the PostgreSQL idempotency module no longer holds exactly the test the isolation "
        f"fixture guards. Fixture guards {POSTGRES_IDEMPOTENCY_TEST!r}; module defines "
        f"{defined_tests!r}. Its destructive cleanup would run unisolated."
    )
