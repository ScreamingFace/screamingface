"""Support: the replay grant settings and their wiring (OME-1307, GW-replay).

FEATURE: OME-1307 (E14) - startup validation of the grant public keys, and what the composition
builds for each combination of the kill switch, the signing key and the grant keys.
INVARIANT (OD-R1): a gateway that cannot verify a grant refuses it with `403 replay_grant_invalid`,
reason `signature`. It never runs the call live.
INVARIANT: the replay half does not depend on the receipt signing key.
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aigateway.config import Settings
from aigateway.core.cache_versions.grant import Ed25519ReplayGrantVerifier
from aigateway.core.cache_versions.lookup import TortoiseCacheVersionLookup
from aigateway.core.cache_versions.stats import CaptureStats
from aigateway.core.cache_versions.wiring import build_cache_version_services
from tests.unit.cache_versions.conftest import (
    BODY_S,
    login_admin,
    mint_grant,
    raw_private_b64,
    raw_public_b64,
)
from tests.unit.test_chat_global_cache_route import _CHAT_PATH


def _settings(**values: object) -> Settings:
    return Settings(**{"_env_file": None, **values})


def _key_map(key: Ed25519PrivateKey, kid: str = "test-kid") -> dict[str, str]:
    return {kid: raw_public_b64(key)}


def _keys(key: Ed25519PrivateKey, kid: str = "test-kid") -> str:
    """The environment form: a JSON object."""
    return json.dumps(_key_map(key, kid))


def test_replay_defaults() -> None:
    settings = _settings()

    assert settings.replay_grant_public_keys == {}
    assert settings.replay_grant_cache_ttl_s == 60.0


def test_the_key_map_is_read_from_a_json_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS", _keys(key, "kid-1"))
    monkeypatch.setenv("AIGW_REPLAY_GRANT_CACHE_TTL_S", "5")

    settings = _settings()

    assert settings.replay_grant_public_keys == {"kid-1": raw_public_b64(key)}
    assert settings.replay_grant_cache_ttl_s == 5.0


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_the_grant_cache_ttl_must_be_a_positive_finite_number(value: str) -> None:
    with pytest.raises(ValueError):
        _settings(AIGW_REPLAY_GRANT_CACHE_TTL_S=value)


# --- wiring -----------------------------------------------------------------------------------


def _wire(**values: object) -> Any:
    return build_cache_version_services(_settings(**values), CaptureStats())


def test_the_lookup_is_always_built() -> None:
    services = _wire()

    assert isinstance(services.lookup, TortoiseCacheVersionLookup)
    assert services.grant_verifier is None


def test_the_flag_off_builds_no_verifier_even_with_keys() -> None:
    key = Ed25519PrivateKey.generate()

    services = _wire(AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS=_key_map(key))

    assert services.grant_verifier is None


def test_the_flag_on_with_no_grant_key_builds_no_verifier() -> None:
    services = _wire(AIGW_CACHE_VERSIONS_ENABLED="true")

    assert services.grant_verifier is None


def test_the_replay_half_does_not_need_the_receipt_signing_key() -> None:
    key = Ed25519PrivateKey.generate()

    services = _wire(
        AIGW_CACHE_VERSIONS_ENABLED="true", AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS=_key_map(key)
    )

    assert isinstance(services.grant_verifier, Ed25519ReplayGrantVerifier)
    assert services.freezer is None, "no signing key: freeze stays off"


def test_a_signing_key_does_not_need_a_grant_key() -> None:
    services = _wire(
        AIGW_CACHE_VERSIONS_ENABLED="true",
        AIGATEWAY_RECEIPT_SIGNING_KEY=raw_private_b64(Ed25519PrivateKey.generate()),
    )

    assert services.freezer is not None
    assert services.grant_verifier is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("!!!not base64!!!", id="not-base64"),
        pytest.param(base64.b64encode(b"\x01" * 31).decode(), id="31-bytes"),
    ],
)
def test_a_bad_public_key_fails_at_startup_and_names_the_kid(
    monkeypatch: pytest.MonkeyPatch, credential_blobs: Any, value: str
) -> None:
    from aigateway.main import create_app

    monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("AIGW_CACHE_VERSIONS_ENABLED", "true")
    monkeypatch.setenv("AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS", json.dumps({"kid-9": value}))

    with pytest.raises(RuntimeError, match=r"AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS\['kid-9'\]"):
        create_app()


# --- OD-R1: a gateway that cannot verify a grant refuses it ---------------------------------------


def _refused_with_signature(client: TestClient, grant: str) -> None:
    resp = client.post(_CHAT_PATH, json=BODY_S, headers={"X-AIGW-Cache-Replay": grant})

    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert (detail["code"], detail["reason"]) == ("replay_grant_invalid", "signature")


def test_a_grant_on_a_gateway_with_no_public_key_is_refused(
    freeze_client: TestClient,
) -> None:
    # `freeze_client`: the flag is on and the signing key is set, but no grant key is configured.
    signer = Ed25519PrivateKey.generate()

    _refused_with_signature(freeze_client, mint_grant(signer, sub="admin", vid="v"))


def test_a_grant_on_a_gateway_with_the_flag_off_is_refused(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    # The keys are set, the kill switch is off: still refused, never a silent live call.
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS", _keys(key))
    login_admin(client)
    assert cast(Any, client.app).state.settings.cache_versions_enabled is False

    _refused_with_signature(client, mint_grant(key, sub="admin", vid="v"))
