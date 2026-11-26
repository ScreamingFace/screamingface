"""The claim route has its own peer list (OME-1947, contracts K4, code review 2026-11-23).

WHY this file exists: the scoreboard is outside the mesh. Before this list, the only way to let it
reach the claim route was to add its pods to `AIGW_ALLOWED_NETWORKS`, and a peer on that list may
name any user in `X-User-Email` on every authenticated route. A peer on
`AIGW_FROZEN_COPY_CLAIM_NETWORKS` may call the claim route and nothing else.

AIDEV-NOTE: the chart tests need `helm` on PATH and skip without it, as the sibling chart tests do.
"""

from __future__ import annotations

import shutil
from ipaddress import ip_network
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.auth.test_allowed_networks import _settings
from tests.unit.test_chart_render_frozen_copy_claim import _config_data
from tests.unit.test_frozen_copy_claim import CLAIMER, _claim_path, _new_copy, _read_copy

MESH_NETWORK = ip_network("10.0.0.0/8")
SCOREBOARD_NETWORK = ip_network("172.20.0.0/16")
SCOREBOARD_PEER = "172.20.1.2"
UNTRUSTED_PEER = "203.0.113.7"
_VAR = "AIGW_FROZEN_COPY_CLAIM_NETWORKS"

_needs_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _header_mode(client, peer: str) -> TestClient:
    settings = client.app.state.settings
    settings.auth_mode = "cloudflare_headers"
    settings.allowed_networks = (MESH_NETWORK,)
    settings.frozen_copy_claim_networks = (SCOREBOARD_NETWORK,)
    settings.admin_emails = frozenset()
    return TestClient(client.app, client=(peer, 50000))


# --- the setting ------------------------------------------------------------------------------


def test_the_setting_parses_a_comma_list_of_networks() -> None:
    settings = _settings(auth_mode="jwt", **{_VAR: " 172.20.0.0/16 , fd00::/8 "})

    assert settings.frozen_copy_claim_networks == (SCOREBOARD_NETWORK, ip_network("fd00::/8"))


def test_the_setting_is_empty_by_default() -> None:
    assert _settings(auth_mode="jwt").frozen_copy_claim_networks == ()


def test_the_setting_refuses_a_network_with_host_bits() -> None:
    with pytest.raises(ValueError):
        _settings(auth_mode="jwt", **{_VAR: "172.20.1.0/8"})


# --- the guard --------------------------------------------------------------------------------


def test_a_peer_on_the_claim_networks_may_claim(authenticated_client: TestClient) -> None:
    copy_id = _new_copy(authenticated_client)
    scoreboard = _header_mode(authenticated_client, SCOREBOARD_PEER)

    resp = scoreboard.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 200
    assert resp.json()["already"] is False
    assert _read_copy(authenticated_client, copy_id).claimed_at is not None


def test_a_peer_on_the_claim_networks_may_claim_with_no_identity_header(
    authenticated_client: TestClient,
) -> None:
    copy_id = _new_copy(authenticated_client)
    scoreboard = _header_mode(authenticated_client, SCOREBOARD_PEER)

    resp = scoreboard.post(_claim_path(copy_id))

    assert resp.status_code == 200
    assert _read_copy(authenticated_client, copy_id).claimed_at is not None


def test_a_peer_on_neither_list_may_not_claim_with_no_identity_header(
    authenticated_client: TestClient,
) -> None:
    copy_id = _new_copy(authenticated_client)
    outsider = _header_mode(authenticated_client, UNTRUSTED_PEER)

    resp = outsider.post(_claim_path(copy_id))

    assert resp.status_code == 403
    assert _read_copy(authenticated_client, copy_id).claimed_at is None


def test_a_peer_on_the_claim_networks_is_not_trusted_on_other_routes(
    authenticated_client: TestClient,
) -> None:
    scoreboard = _header_mode(authenticated_client, SCOREBOARD_PEER)

    resp = scoreboard.get("/v1/auth/me", headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 403


def test_a_peer_on_neither_list_may_not_claim(authenticated_client: TestClient) -> None:
    copy_id = _new_copy(authenticated_client)
    outsider = _header_mode(authenticated_client, UNTRUSTED_PEER)

    resp = outsider.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 403
    assert _read_copy(authenticated_client, copy_id).claimed_at is None


def test_a_mesh_peer_may_still_claim(authenticated_client: TestClient) -> None:
    copy_id = _new_copy(authenticated_client)
    mesh = _header_mode(authenticated_client, "10.1.2.3")

    resp = mesh.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 200


# --- the chart --------------------------------------------------------------------------------


@_needs_helm
def test_the_chart_renders_an_empty_claim_network_list_by_default(tmp_path: Path) -> None:
    data = _config_data(tmp_path)

    assert data[_VAR] == ""
    assert _settings(auth_mode="jwt", **{_VAR: data[_VAR]}).frozen_copy_claim_networks == ()


@_needs_helm
def test_the_chart_renders_the_claim_networks_apart_from_the_allowed_networks(
    tmp_path: Path,
) -> None:
    data = _config_data(
        tmp_path,
        {
            "config": {
                "allowedNetworks": ["10.0.0.0/8"],
                "frozenCopyClaimNetworks": ["172.20.0.0/16", "fd00::/8"],
            }
        },
    )

    assert data[_VAR] == "172.20.0.0/16,fd00::/8"
    assert "172.20.0.0/16" not in data["AIGW_ALLOWED_NETWORKS"]
    settings = _settings(auth_mode="jwt", **{_VAR: data[_VAR]})
    assert settings.frozen_copy_claim_networks == (SCOREBOARD_NETWORK, ip_network("fd00::/8"))
