"""`Settings` is the sole authority on this service's environment.

The parsing cases below all exist for one reason: pydantic-settings JSON-decodes complex field
types read from the environment, so a comma-separated list arrives as malformed JSON and fails
before any validator runs. `NoDecode` is what moves the parse into our own hands.
"""

from __future__ import annotations

from ipaddress import ip_network

import pytest

from report_intake.config import ENV_PREFIX, Settings


def _settings(**values: object) -> Settings:
    """Build Settings from raw values, as the environment supplies them.

    `model_validate` rather than the constructor because `allowed_networks` arrives as a
    comma-separated STRING and is parsed into networks — which is the behaviour under test.
    """
    return Settings.model_validate(values)


def test_a_comma_separated_cidr_list_becomes_networks() -> None:
    settings = _settings(allowed_networks="10.0.0.0/8,192.168.0.0/16")

    assert settings.allowed_networks == (ip_network("10.0.0.0/8"), ip_network("192.168.0.0/16"))


def test_a_cidr_list_read_from_the_environment_is_not_treated_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `NoDecode` case, exercised through the environment rather than through a dict —
    without it this value never reaches the validator at all."""
    monkeypatch.setenv("REPORT_INTAKE_ALLOWED_NETWORKS", "10.0.0.0/8")

    assert Settings().allowed_networks == (ip_network("10.0.0.0/8"),)


def test_surrounding_whitespace_is_tolerated() -> None:
    settings = _settings(allowed_networks=" 10.0.0.0/8 , 172.16.0.0/12 ")

    assert settings.allowed_networks == (ip_network("10.0.0.0/8"), ip_network("172.16.0.0/12"))


def test_an_empty_value_is_no_networks() -> None:
    assert _settings(allowed_networks="").allowed_networks == ()


def test_a_network_with_host_bits_set_is_refused() -> None:
    """Refused rather than silently widened: `strict=False` would turn `192.168.0.0/8` into
    `192.0.0.0/8` and trust sixteen million addresses the operator never named."""
    with pytest.raises(ValueError, match="host bits"):
        _settings(allowed_networks="192.168.0.0/8")


def test_the_environment_supplies_the_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPORT_INTAKE_LOG_LEVEL", "debug")

    assert Settings().log_level == "debug"


def test_the_service_listens_on_its_own_port_by_default() -> None:
    """9105 aigateway, 9106 scoreboard, 9107 aigateway-ui, 9108 engine — this one is 9109. A
    collision is not a crash on a developer's machine, it is two services silently sharing a
    port depending on start order."""
    assert Settings().port == 9109


def test_the_database_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Named as a field, which is what makes it usable at all: `create_app` refuses to start on
    a `REPORT_INTAKE_*` variable no field reads, so the field and its reader land together."""
    monkeypatch.setenv("REPORT_INTAKE_DATABASE_URL", "postgres://user@db:5432/reports")

    assert Settings().database_url == "postgres://user@db:5432/reports"


def test_the_relative_sqlite_spelling_is_rewritten_rather_than_written_to_the_root() -> None:
    """`sqlite:///report-intake.sqlite3` reads as "relative file" to almost everyone and means
    `/report-intake.sqlite3` to the driver — a path the container's unprivileged service user
    cannot write, surfacing at the first report rather than at startup."""
    assert _settings(database_url="sqlite:///report-intake.sqlite3").database_url == (
        "sqlite://./report-intake.sqlite3"
    )


def test_an_absolute_sqlite_path_is_left_alone() -> None:
    """The rewrite is for the ambiguous one-segment spelling only. An operator who named a real
    directory meant it."""
    assert _settings(database_url="sqlite:///var/lib/report-intake/db.sqlite3").database_url == (
        "sqlite:///var/lib/report-intake/db.sqlite3"
    )


def test_the_idempotency_window_defaults_to_the_scoreboards_twenty_four_hours() -> None:
    """Spec §5 matches it deliberately: a client retrying against two ScreamingFace services
    should not have to learn two windows."""
    assert Settings().idempotency_ttl_h == 24


def test_row_retention_defaults_to_ninety_days() -> None:
    """The ticket is the durable artifact; the row exists for idempotency, retry, and forensics
    (spec §5)."""
    assert Settings().retention_days == 90


def test_the_ticket_sink_is_named_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A field, which is what makes the name usable at all: `create_app` refuses to start on a
    `REPORT_INTAKE_*` variable no field reads, so the field and its reader land together."""
    monkeypatch.setenv("REPORT_INTAKE_TICKET_SINK", "queue")

    assert Settings().ticket_sink == "queue"


def test_the_linear_credentials_are_empty_until_a_deployment_supplies_them() -> None:
    """Empty is what keeps the adapter inert. CLAUDE.md rule 9 governs selecting it, and shipping
    the code must not select it: `build_sink` refuses to start a `linear` deployment that has no
    credential rather than accepting reports and filing none of them."""
    settings = Settings()

    assert settings.linear_api_key.get_secret_value() == ""
    assert settings.linear_team_id == ""


def test_the_linear_api_key_does_not_survive_a_repr_of_these_settings() -> None:
    """`SecretStr`, like the Turnstile secret: a long-lived token to the private tracker the team
    works in has to be safe near a traceback or a debug dump, rather than relying on nobody ever
    printing `Settings`."""
    settings = _settings(linear_api_key="lin_api_notreal")

    assert "lin_api_notreal" not in repr(settings)
    assert settings.linear_api_key.get_secret_value() == "lin_api_notreal"


def test_the_linear_endpoint_is_defaulted_rather_than_asked_for() -> None:
    """There is exactly one of them, so an operator who had to type it could only get it wrong.
    A field rather than a constant so a test — or a proxied deployment — can move it."""
    assert Settings().linear_api_url == "https://api.linear.app/graphql"


def test_the_linear_deadline_matches_the_inline_delivery_one() -> None:
    """The dispatcher's `asyncio.wait_for` is the outer bound; this one exists so the HTTP client
    gives up by itself rather than being cancelled mid-flight. Raising it past the delivery
    timeout buys nothing — the outer deadline still fires first."""
    settings = Settings()

    assert settings.linear_timeout_s == settings.delivery_timeout_s


def test_the_inline_delivery_deadline_defaults_to_the_specs_three_seconds() -> None:
    """Spec §2.2 and §6, not the drafting pass's 10 s (plan §11 conflict 18). Past the deadline
    the row stays `pending` and the response is still `202`, so a larger number does not make
    delivery more likely — it only makes filing a bug slower."""
    assert Settings().delivery_timeout_s == 3.0


def test_the_auth_posture_defaults_to_the_loopback_only_one() -> None:
    """The failure direction matters: a deployment that forgets to set this is a local-only
    process that refuses network callers, not an open one."""
    assert Settings().auth_mode == "disabled"


def test_the_auth_posture_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPORT_INTAKE_AUTH_MODE", "mesh_or_turnstile")

    assert Settings().auth_mode == "mesh_or_turnstile"


def test_a_posture_this_service_does_not_implement_is_refused() -> None:
    """A typo here is the mismatch plan §2.4 exists to catch: with `extra="ignore"` and no
    literal, `auth_mode="mesh-or-turnstile"` would boot a pod with a posture nobody wrote."""
    with pytest.raises(ValueError, match="auth_mode"):
        _settings(auth_mode="mesh-or-turnstile")


def test_the_client_ip_header_is_not_trusted_by_default() -> None:
    """Trusting it would mean trusting it always, since the mesh proxy is the peer on every
    request — and a rotated header would then buy a fresh rate-limit bucket per request."""
    assert Settings().trust_client_ip_header is False


def test_cors_origins_are_a_comma_separated_list_not_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `NoDecode` case again, through the environment: without it this value is JSON-decoded
    and dies before the validator runs."""
    monkeypatch.setenv(
        "REPORT_INTAKE_CORS_ORIGINS", "https://a.example.test, https://b.example.test"
    )

    assert Settings().cors_origins == ("https://a.example.test", "https://b.example.test")


def test_no_cors_origins_is_the_default() -> None:
    """An empty allowlist is not an allowlist of everything: `create_app` installs no CORS
    middleware at all rather than one that announces a permissive policy."""
    assert Settings().cors_origins == ()


def test_the_turnstile_secret_is_empty_until_a_deployment_supplies_one() -> None:
    """From a Secret, never a default. `create_app` refuses to run the deployed posture without
    it rather than shipping a placeholder that siteverify would reject."""
    assert Settings().turnstile_secret.get_secret_value() == ""


def test_the_turnstile_secret_does_not_survive_a_repr_of_these_settings() -> None:
    """`SecretStr`, so the value is safe near a traceback or a debug dump rather than relying on
    nobody ever printing `Settings` — which is the rule everyone eventually forgets."""
    settings = _settings(turnstile_secret="the-real-secret")

    assert "the-real-secret" not in repr(settings)
    assert settings.turnstile_secret.get_secret_value() == "the-real-secret"


def test_the_site_key_is_not_a_setting() -> None:
    """It is a browser-side value this process never reads; rendering it into the pod would be
    cargo cult (plan §2.4). Asserted so a chart cannot quietly reintroduce it — `create_app`
    refuses to start on a `REPORT_INTAKE_*` name matching no field."""
    assert "turnstile_site_key" not in Settings.model_fields


def test_the_anonymous_budget_has_a_burst_smaller_than_its_sustained_rate() -> None:
    """A human filing a bug report sends one request, occasionally two after a retry. The burst is
    what a legitimate double-click needs, not what a submission loop needs."""
    settings = Settings()

    assert settings.anon_rate_burst < settings.anon_rate_limit
    assert settings.anon_rate_window_s == 60


@pytest.mark.parametrize(
    "field", ["anon_rate_limit", "anon_rate_window_s", "anon_rate_burst", "anon_rate_max_keys"]
)
def test_a_zero_rate_limit_setting_is_refused(field: str) -> None:
    """Each is a divisor or a capacity: a zero rate divides by zero inside the bucket and a zero
    burst is a service that admits nobody."""
    with pytest.raises(ValueError, match=field):
        _settings(**{field: 0})


_PLAN_ENVIRONMENT_SURFACE = frozenset(
    {
        "REPORT_INTAKE_HOST",
        "REPORT_INTAKE_PORT",
        "REPORT_INTAKE_LOG_LEVEL",
        "REPORT_INTAKE_DATABASE_URL",
        "REPORT_INTAKE_TICKET_SINK",
        "REPORT_INTAKE_DELIVERY_TIMEOUT_S",
        "REPORT_INTAKE_IDEMPOTENCY_TTL_H",
        "REPORT_INTAKE_RETENTION_DAYS",
        "REPORT_INTAKE_AUTH_MODE",
        "REPORT_INTAKE_ALLOWED_NETWORKS",
        "REPORT_INTAKE_CORS_ORIGINS",
        "REPORT_INTAKE_TRUST_CLIENT_IP_HEADER",
        "REPORT_INTAKE_TURNSTILE_SECRET",
        "REPORT_INTAKE_TURNSTILE_VERIFY_URL",
        "REPORT_INTAKE_TURNSTILE_TIMEOUT_S",
        "REPORT_INTAKE_ANON_RATE_LIMIT",
        "REPORT_INTAKE_ANON_RATE_WINDOW_S",
        "REPORT_INTAKE_ANON_RATE_MAX_KEYS",
        "REPORT_INTAKE_ANON_RATE_BURST",
        # OME-1009's amendment, recorded in plan §2.4 rather than only here: the four fields the
        # `linear` sink reads. All four are inert unless `TICKET_SINK` names it, and the chart
        # renders all four regardless — a field the chart never renders can only ever hold its
        # declared default in production, which is the failure this equality exists to catch.
        "REPORT_INTAKE_LINEAR_API_KEY",
        "REPORT_INTAKE_LINEAR_TEAM_ID",
        "REPORT_INTAKE_LINEAR_API_URL",
        "REPORT_INTAKE_LINEAR_TIMEOUT_S",
    }
)
"""Plan §2.4's frozen list, transcribed. `FORWARDED_ALLOW_IPS` is deliberately absent: it is
uvicorn's own, unprefixed, and is the one name this service cares about that is not a field.

The list is frozen, not sealed: a name is added HERE and in plan §2.4 together, by the item that
adds the field. What it forbids is a field arriving with neither."""


def test_the_environment_surface_is_exactly_the_one_the_plan_froze() -> None:
    """The chart renders this set and nothing else, so the two have to be enumerable and equal.

    `create_app`'s startup guard catches a chart name no field reads; this catches the other
    direction — a field added without the chart learning about it, which is a setting that can
    only ever hold its default in production. Together they are the app-side half of plan §2.4;
    `verify_chart_wiring.py` is the chart-side half.
    """
    rendered = {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}

    assert rendered == _PLAN_ENVIRONMENT_SURFACE
