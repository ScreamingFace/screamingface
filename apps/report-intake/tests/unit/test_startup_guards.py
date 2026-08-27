"""Every startup guard refuses a configuration that would otherwise boot and be wrong.

They live in `create_app` rather than on `Settings` because none is a check on a single field:
one is about a name `Settings` never saw, one about an environment variable `Settings` does not
own, one about two fields that only make sense together. All three failures look exactly like
success from the outside — a pod that starts, answers its probes, and is wrong about who its
callers are.
"""

from __future__ import annotations

import pytest
import uvicorn
from fastapi.testclient import TestClient

from report_intake.config import Settings
from report_intake.main import _UVICORN_DEFAULT_FORWARDED_ALLOW_IPS, create_app


def _settings(**values: object) -> Settings:
    return Settings.model_validate(values)


# --- a REPORT_INTAKE_* name that matches no field ---------------------------------------------
#
# `extra="ignore"` accepts, drops, and never mentions such a name, so the field keeps its
# DEFAULT. For `AUTH_MODE` that is a production pod running with authentication disabled.


def test_a_report_intake_variable_matching_no_field_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPORT_INTAKE_IDENTITY_MODE", "mesh_or_turnstile")

    with pytest.raises(ValueError, match="REPORT_INTAKE_IDENTITY_MODE"):
        create_app(_settings())


def test_the_refusal_lists_the_names_that_would_have_worked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guard that says only "unknown variable" leaves an operator diffing a chart against a
    Python class. The message is the fix."""
    monkeypatch.setenv("REPORT_INTAKE_TRUSTED_PROXY_NETWORKS", "10.0.0.0/8")

    with pytest.raises(ValueError, match="REPORT_INTAKE_ALLOWED_NETWORKS"):
        create_app(_settings())


def test_a_lowercase_spelling_is_caught_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """pydantic-settings matches environment names case-insensitively, so a guard that only
    looked at upper-case keys would wave through the same mistake in lower case."""
    monkeypatch.setenv("report_intake_identity_mode", "mesh_or_turnstile")

    with pytest.raises(ValueError, match="report_intake_identity_mode"):
        create_app(_settings())


def test_a_variable_that_does_match_a_field_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPORT_INTAKE_LOG_LEVEL", "debug")

    assert create_app(_settings()).state.settings is not None


def test_an_unprefixed_variable_is_none_of_this_guard_s_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH_TO_NOWHERE", "x")

    assert create_app(_settings()).state.settings is not None


# --- FORWARDED_ALLOW_IPS versus the networks that may present an identity ----------------------
#
# Declaring `allowed_networks` means something is about to trust `request.client.host`. Uvicorn's
# ProxyHeadersMiddleware overwrites that value from a client-supplied X-Forwarded-For whenever
# the peer falls inside FORWARDED_ALLOW_IPS — so the two settings must be disjoint, and "*"
# matches every peer with no proxy relationship required.


def test_declared_networks_refuse_a_wildcard_forwarded_allow_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")

    with pytest.raises(ValueError, match="FORWARDED_ALLOW_IPS"):
        create_app(_settings(allowed_networks="10.0.0.0/8"))


def test_declared_networks_refuse_a_bare_address_inside_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scoping the value away from "*" is not enough on its own: one deliberately narrow address
    inside `allowed_networks` lets uvicorn rewrite the peer for exactly the peers the check
    exists to authenticate."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.5")

    with pytest.raises(ValueError, match="overlaps"):
        create_app(_settings(allowed_networks="10.0.0.0/8"))


def test_declared_networks_refuse_an_overlapping_cidr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.0/16")

    with pytest.raises(ValueError, match="overlaps"):
        create_app(_settings(allowed_networks="10.0.0.0/8"))


def test_declared_networks_refuse_an_ipv4_mapped_ipv6_entry_naming_the_same_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator naming the same real peer in the form a dual-stack cluster reports it must
    trip the guard exactly as the plain IPv4 form does."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "::ffff:10.0.0.5")

    with pytest.raises(ValueError, match="overlaps"):
        create_app(_settings(allowed_networks="10.0.0.0/8"))


def test_declared_networks_refuse_a_list_where_only_one_entry_overlaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the guard classifies the value per entry rather than as one opaque string — a
    harmless IPv6 entry must not mask a real IPv4 overlap beside it."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "fd00::1,10.0.0.5")

    with pytest.raises(ValueError, match="overlaps"):
        create_app(_settings(allowed_networks="10.0.0.0/8"))


def test_declared_networks_refuse_an_ipv6_overlap_of_their_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-version cases prove the guard does not false-positive; this proves it does not
    false-negative within a single version either."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "fd00::/16")

    with pytest.raises(ValueError, match="overlaps"):
        create_app(_settings(allowed_networks="fd00::/8"))


def test_declared_networks_start_with_a_disjoint_forwarded_allow_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.0/24")

    assert create_app(_settings(allowed_networks="10.0.0.0/8")).state.settings.allowed_networks


def test_declared_networks_start_against_an_ipv6_entry_that_cannot_reach_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "fd00::1")

    assert create_app(_settings(allowed_networks="10.0.0.0/8")).state.settings.allowed_networks


def test_declared_networks_start_against_entries_uvicorn_itself_could_never_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard predicts uvicorn's forgiving parsing rather than adding strictness of its own.

    A hostname, an empty entry, and a host-bits-set CIDR are all inert for uvicorn — it cannot
    match a real peer against any of them — so none of them can be an overlap, and refusing them
    here would reject a configuration that is actually harmless. Note the difference from
    `REPORT_INTAKE_ALLOWED_NETWORKS`, where a host-bits-set entry IS refused: that value is ours
    and a silent widening there trusts addresses nobody named.
    """
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "localhost,,10.0.0.5/8")

    assert create_app(_settings(allowed_networks="10.0.0.0/8")).state.settings.allowed_networks


def test_declared_networks_start_with_forwarded_allow_ips_unset() -> None:
    """uvicorn's own fallback is the loopback, which is safe — only an explicit wildcard or a
    real overlap should trip the guard."""
    assert create_app(_settings(allowed_networks="10.0.0.0/8")).state.settings.allowed_networks


def test_no_declared_networks_leaves_forwarded_allow_ips_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard is scoped to the configuration that needs it. With no declared networks nothing
    reads `request.client.host` for a security decision, and "*" is the value a Traefik-fronted
    deployment legitimately sets."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")

    assert create_app(_settings()).state.settings.allowed_networks == ()


def test_uvicorn_still_falls_back_to_the_loopback_for_forwarded_allow_ips() -> None:
    """Pins the constant the guard reasons about against the INSTALLED uvicorn.

    `_UVICORN_DEFAULT_FORWARDED_ALLOW_IPS` is a copy of a value uvicorn owns. If a future
    `uv lock --upgrade` changes that default to something permissive, the guard would go on
    believing an unset variable is safe. This is what breaks instead.
    """

    async def _app(scope: object, receive: object, send: object) -> None: ...  # pragma: no cover

    config = uvicorn.Config(app=_app)

    assert config.forwarded_allow_ips == _UVICORN_DEFAULT_FORWARDED_ALLOW_IPS


# --- a `mesh_or_turnstile` app that cannot run either half of its gate ------------------------
#
# Spec §7's two caller classes are not alternatives an operator picks between: every request is
# one or the other, so a missing half silently turns that whole class away while the pod keeps
# reporting itself healthy and ready.


def test_the_deployed_auth_mode_refuses_to_start_without_declared_networks() -> None:
    """`peer_in_networks` denies everything with no networks, so nothing could ever be
    mesh-verified and even the mesh's own callers would be sent to the bot gate. There is also no
    value to guess: "which networks?" is a fact about the deployment."""
    with pytest.raises(ValueError, match="REPORT_INTAKE_ALLOWED_NETWORKS"):
        create_app(_settings(auth_mode="mesh_or_turnstile", turnstile_secret="s3cret"))


def test_the_deployed_auth_mode_refuses_to_start_without_a_turnstile_secret() -> None:
    """Siteverify rejects our own credentials, which this service correctly reads as an
    unevaluable gate — so every anonymous report would be answered `503`, forever."""
    with pytest.raises(ValueError, match="REPORT_INTAKE_TURNSTILE_SECRET"):
        create_app(_settings(auth_mode="mesh_or_turnstile", allowed_networks="10.0.0.0/8"))


def test_the_deployed_auth_mode_starts_when_both_halves_are_configured() -> None:
    app = create_app(
        _settings(
            auth_mode="mesh_or_turnstile", allowed_networks="10.0.0.0/8", turnstile_secret="s3cret"
        )
    )

    assert app.state.turnstile_verifier is not None


def test_the_local_auth_mode_needs_neither(client: TestClient) -> None:
    """`disabled` has no anonymous caller class to gate and no mesh to be verified by, so it
    builds no verifier — and a service that constructed an HTTP client for every app a test builds
    would be a resource nobody closes."""
    assert client.app.state.turnstile_verifier is None  # type: ignore[attr-defined]


def test_the_verifier_the_app_built_is_closed_on_shutdown() -> None:
    """It owns an HTTP client, and a process that reloaded its app in a test would otherwise leak
    one per build. Closing is scoped to the verifier `create_app` made: a test that swapped its own
    onto the seam owns that one, and calling `aclose` on a fake would make installing one an error
    at teardown."""
    app = create_app(
        _settings(
            auth_mode="mesh_or_turnstile", allowed_networks="10.0.0.0/8", turnstile_secret="s3cret"
        )
    )

    with TestClient(app, base_url="http://r.example.test", client=("10.1.2.3", 50000)) as c:
        assert c.get("/healthz").status_code == 200


# --- an inline delivery attempt that outlasts the retry sweep's claim grace --------------------
#
# `config.deliveryTimeoutS` is a live chart knob and `CLAIM_GRACE` is a constant in another
# module, so the relation between them is one nothing enforced. A unit test pinning the arithmetic
# proves it for config.py's DEFAULT and says nothing about the value a deployment renders — which
# is the only one that can reopen the sweeper-vs-request-path double-ticket window.


def test_a_delivery_timeout_that_outlasts_the_retry_claim_grace_refuses_to_start() -> None:
    """25 s + the two 5 s storage deadlines is a 35 s inline attempt against a 30 s grace: a
    sweeper on another replica would claim a report the request path is still filing, and one bug
    report becomes two tickets with nothing red anywhere."""
    with pytest.raises(ValueError, match="REPORT_INTAKE_DELIVERY_TIMEOUT_S"):
        create_app(_settings(delivery_timeout_s=25))


def test_the_refusal_names_the_grace_it_would_have_outlasted() -> None:
    """An operator who typed a number needs to know which other number it collided with — the
    grace lives in `reports/retry.py` and is not a value they can see from the chart."""
    with pytest.raises(ValueError, match="two tickets"):
        create_app(_settings(delivery_timeout_s=25))


def test_a_delivery_timeout_exactly_as_long_as_the_grace_is_refused_too() -> None:
    """20 s makes the worst-case attempt exactly the 30 s grace. Equal is not shorter: the sweep
    would become due at the instant the attempt is still in flight, which is the window itself."""
    with pytest.raises(ValueError, match="REPORT_INTAKE_DELIVERY_TIMEOUT_S"):
        create_app(_settings(delivery_timeout_s=20))


def test_a_delivery_timeout_the_grace_still_covers_starts() -> None:
    """The guard bounds the knob, it does not pin it to the spec's 3 s — a deployment with a slow
    sink may legitimately raise it, as far as the grace allows."""
    assert create_app(_settings(delivery_timeout_s=19)).state.settings.delivery_timeout_s == 19


def test_the_spec_s_own_delivery_timeout_starts() -> None:
    """Spec §2.2's number, which is also config.py's default — the guard must not refuse the
    configuration every deployment of this chart actually renders."""
    assert create_app(_settings()).state.settings.delivery_timeout_s == 3.0
