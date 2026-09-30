"""`screamingface up` makes the local Ed25519 signing keys once (E14, OME-1307, RP-20).

FEATURE: OME-1307 (E14). A local stack has a gateway that signs receipts and a scoreboard that
verifies them (C3), and a scoreboard that signs replay grants and a gateway that verifies them
(C6). `up` makes both keypairs once, keeps them in a private file, and hands each service its half
by environment before any service starts (contract: SDK-replay plan §4.12).

INVARIANT: the two halves of one group always come from one pair. A signer from one pair and a
verifier from another fail every submit or replay with no clue, so a partly set group is an error.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from nacl.signing import SigningKey, VerifyKey

from screamingface._runtime import server
from screamingface._runtime.config import RuntimeConfig
from screamingface._runtime.signing_keys import (
    KEY_FILENAME,
    LocalSigningKeys,
    apply_local_signing_environment,
    ensure_local_signing_keys,
)

RECEIPT_ENV = ("AIGATEWAY_RECEIPT_SIGNING_KEY", "SCOREBOARD_RECEIPT_PUBLIC_KEYS")
GRANT_ENV = (
    "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY",
    "SCOREBOARD_REPLAY_GRANT_SIGNING_KID",
    "AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS",
)
ALL_ENV = RECEIPT_ENV + GRANT_ENV


def _raw(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def _sign_and_verify(seed_b64: str, public_b64: str) -> None:
    signed = SigningKey(_raw(seed_b64)).sign(b"x")
    VerifyKey(_raw(public_b64)).verify(b"x", signed.signature)


def test_rp20_first_start_creates_two_pairs_in_a_private_file(tmp_path: Path) -> None:
    keys = ensure_local_signing_keys(tmp_path)

    path = tmp_path / KEY_FILENAME
    assert path.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert keys.receipt.kid != keys.replay_grant.kid
    assert keys.receipt.private_key != keys.replay_grant.private_key
    assert not list(tmp_path.glob("*.tmp"))


def test_rp20_the_kids_and_key_forms_follow_the_service_contracts(tmp_path: Path) -> None:
    keys = ensure_local_signing_keys(tmp_path)

    for pair in (keys.receipt, keys.replay_grant):
        assert len(_raw(pair.private_key)) == 32
        assert len(_raw(pair.public_key)) == 32
        _sign_and_verify(pair.private_key, pair.public_key)
    digest = hashlib.sha256(base64.b64decode(keys.receipt.public_key)).hexdigest()[:16]
    # INVARIANT: the gateway derives the receipt kid (GW-freeze OD-F2), so any other value here
    # makes the scoreboard map miss the kid and every receipt fail with 422.
    assert keys.receipt.kid == digest
    grant_digest = hashlib.sha256(base64.b64decode(keys.replay_grant.public_key)).hexdigest()[:16]
    assert keys.replay_grant.kid == f"local-{grant_digest}"


def test_rp20_a_private_key_never_shows_in_a_repr(tmp_path: Path) -> None:
    keys = ensure_local_signing_keys(tmp_path)

    assert keys.receipt.private_key not in repr(keys)
    assert keys.replay_grant.private_key not in repr(keys)


def test_rp20_second_start_reuses_the_same_keys(tmp_path: Path) -> None:
    first = ensure_local_signing_keys(tmp_path)
    before = (tmp_path / KEY_FILENAME).read_bytes()

    second = ensure_local_signing_keys(tmp_path)

    assert isinstance(second, LocalSigningKeys)
    assert second == first
    assert (tmp_path / KEY_FILENAME).read_bytes() == before


def test_rp20_a_data_dir_that_does_not_exist_yet_is_made(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"

    ensure_local_signing_keys(nested)

    assert (nested / KEY_FILENAME).is_file()


def test_rp20_environment_pairs_sign_and_verify(tmp_path: Path) -> None:
    environment: dict[str, str] = {}

    apply_local_signing_environment(environment, tmp_path)

    keys = ensure_local_signing_keys(tmp_path)
    assert set(environment) == set(ALL_ENV)
    receipt_map = json.loads(environment["SCOREBOARD_RECEIPT_PUBLIC_KEYS"])
    assert list(receipt_map) == [keys.receipt.kid]
    _sign_and_verify(environment["AIGATEWAY_RECEIPT_SIGNING_KEY"], receipt_map[keys.receipt.kid])
    grant_map = json.loads(environment["AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS"])
    kid = environment["SCOREBOARD_REPLAY_GRANT_SIGNING_KID"]
    assert list(grant_map) == [kid] == [keys.replay_grant.kid]
    _sign_and_verify(environment["SCOREBOARD_REPLAY_GRANT_SIGNING_KEY"], grant_map[kid])


def test_rp20_the_signer_of_a_group_never_verifies_with_the_other_groups_key(
    tmp_path: Path,
) -> None:
    environment: dict[str, str] = {}
    apply_local_signing_environment(environment, tmp_path)
    receipt_map = json.loads(environment["SCOREBOARD_RECEIPT_PUBLIC_KEYS"])
    grant_map = json.loads(environment["AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS"])

    signed = SigningKey(_raw(environment["AIGATEWAY_RECEIPT_SIGNING_KEY"])).sign(b"x")

    with pytest.raises(Exception):  # noqa: B017, PT011 - nacl raises BadSignatureError
        VerifyKey(_raw(next(iter(grant_map.values())))).verify(b"x", signed.signature)
    assert next(iter(receipt_map.values())) != next(iter(grant_map.values()))


def test_rp20_a_second_apply_gives_the_same_environment(tmp_path: Path) -> None:
    first: dict[str, str] = {}
    second: dict[str, str] = {}

    apply_local_signing_environment(first, tmp_path)
    apply_local_signing_environment(second, tmp_path)

    assert first == second


@pytest.mark.parametrize("group", [RECEIPT_ENV, GRANT_ENV], ids=["receipt", "grant"])
def test_rp20_operator_group_wins(tmp_path: Path, group: tuple[str, ...]) -> None:
    environment = {name: f"operator-{name}" for name in group}

    apply_local_signing_environment(environment, tmp_path)

    for name in group:
        assert environment[name] == f"operator-{name}"
    other = set(ALL_ENV) - set(group)
    assert other <= set(environment)


@pytest.mark.parametrize("group", [RECEIPT_ENV, GRANT_ENV], ids=["receipt", "grant"])
def test_rp20_a_partial_group_fails(tmp_path: Path, group: tuple[str, ...]) -> None:
    for preset in group:
        environment = {preset: "operator"}

        with pytest.raises(RuntimeError, match="set all of") as caught:
            apply_local_signing_environment(environment, tmp_path)

        assert all(name in str(caught.value) for name in group)
        assert "or none of them" in str(caught.value)
        # INVARIANT: a refused start half-applies nothing, so no service sees one group of keys.
        assert environment == {preset: "operator"}


def test_rp20_unreadable_key_file_fails_without_key_text(tmp_path: Path) -> None:
    (tmp_path / KEY_FILENAME).write_text("{")

    with pytest.raises(RuntimeError) as caught:
        ensure_local_signing_keys(tmp_path)

    assert str(tmp_path / KEY_FILENAME) in str(caught.value)
    assert "move the file away" in str(caught.value)


def _valid_file(tmp_path: Path) -> dict[str, Any]:
    ensure_local_signing_keys(tmp_path)
    return json.loads((tmp_path / KEY_FILENAME).read_text())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: [],
        lambda value: {**value, "version": 2},
        lambda value: {key: item for key, item in value.items() if key != "replay_grant"},
        lambda value: {**value, "receipt": {**value["receipt"], "public_key": 5}},
        lambda value: {**value, "receipt": {"kid": value["receipt"]["kid"]}},
        lambda value: {**value, "replay_grant": "text"},
    ],
    ids=["list", "version", "missing-group", "bad-type", "missing-key", "group-not-object"],
)
def test_rp20_a_file_of_the_wrong_shape_fails_without_key_text(tmp_path: Path, mutate: Any) -> None:
    value = _valid_file(tmp_path)
    secrets = [value["receipt"]["private_key"], value["replay_grant"]["private_key"]]
    (tmp_path / KEY_FILENAME).write_text(json.dumps(mutate(value)))

    with pytest.raises(RuntimeError) as caught:
        ensure_local_signing_keys(tmp_path)

    assert str(tmp_path / KEY_FILENAME) in str(caught.value)
    assert not any(secret in str(caught.value) for secret in secrets)


class _Stop(Exception):  # noqa: N818 - a private test signal
    pass


class _Source:
    def describe(self) -> str:
        return "test source"


def test_rp20_up_sets_the_keys_before_the_apps_are_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # WHY set-then-delete: `monkeypatch` only restores a name it saw, and `run` sets these five
    # names on the real `os.environ`. The setenv makes the teardown remove them again.
    for name in ALL_ENV:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    seen: dict[str, str] = {}
    calls: list[str] = []

    async def migrate(config: RuntimeConfig) -> None:
        calls.append("migrate")
        # INVARIANT: the keys are in place before ANY service step, not just before the apps.
        assert set(ALL_ENV) <= set(os.environ)

    def build_apps(config: RuntimeConfig) -> Any:
        calls.append("build_apps")
        seen.update(os.environ)
        raise _Stop

    # WHY `pin_litellm_redaction` is stubbed: `run` also pins litellm redaction, which imports
    # litellm; the `runtime` extra is not installed in the default test lane and this test is
    # about key order, not redaction.
    stubs = {
        "require_runtime_extra": lambda: _Source(),
        "pin_litellm_redaction": lambda: None,
        "_migrate": migrate,
        "_build_apps": build_apps,
    }
    for name, stub in stubs.items():
        monkeypatch.setattr(server, name, stub)
    runner = tmp_path / "url4.toml"
    runner.write_text("")
    config = RuntimeConfig(data_dir=tmp_path / "data", runner_config=runner)

    with pytest.raises(_Stop):
        asyncio.run(server.run(config))

    assert calls == ["migrate", "build_apps"]
    assert set(ALL_ENV) <= set(seen)
    printed = capsys.readouterr().out
    keys = ensure_local_signing_keys(config.data_dir)
    assert keys.receipt.private_key not in printed
    assert keys.replay_grant.private_key not in printed
    assert seen["AIGATEWAY_RECEIPT_SIGNING_KEY"] == keys.receipt.private_key
