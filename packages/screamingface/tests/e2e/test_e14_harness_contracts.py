"""Contract tests for the E14 E2E harness (unit E2E, OME-1307).

These run in the DEFAULT test lane: no docker, no subprocess, no network. They pin what the
five E14 spines stand on: the stack env carries keys of the right shape to the right service,
the test edge sets exactly one verified identity, and no child can get a secret or a second
auth mode.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import MutableMapping
from pathlib import Path

import harness.e14_env as e14_env_module
import httpx
import pytest
from harness.cache_seeded import CacheSeededGateway
from harness.e14_env import e14_env, split_env
from harness.identity import EdgeIdentityTransport
from harness.scoreboard_proc import ScoreboardProcess
from harness.stack import EngineProcess
from nacl.signing import SigningKey, VerifyKey

from screamingface._runtime.local_features import (
    apply_local_e14_environment,
    local_archive_dir,
)

_RECEIPT_PRIVATE = "AIGATEWAY_RECEIPT_SIGNING_KEY"
_RECEIPT_PUBLIC = "SCOREBOARD_RECEIPT_PUBLIC_KEYS"
_GRANT_PRIVATE = "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY"
_GRANT_KID = "SCOREBOARD_REPLAY_GRANT_SIGNING_KID"
_GRANT_PUBLIC = "AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS"
_KEY_NAMES = frozenset(
    {_RECEIPT_PRIVATE, _RECEIPT_PUBLIC, _GRANT_PRIVATE, _GRANT_KID, _GRANT_PUBLIC}
)


def _assert_pair_signs(private_b64: str, public_b64: str) -> bytes:
    """A signature made with the seed verifies with the public key. Returns the raw public key."""
    seed = base64.b64decode(private_b64, validate=True)
    public_raw = base64.b64decode(public_b64, validate=True)
    assert len(seed) == 32
    assert len(public_raw) == 32
    message = b"e14-e2e-key-pair-check"
    VerifyKey(public_raw).verify(SigningKey(seed).sign(message))
    return public_raw


def test_e14_env_keys_come_from_the_local_runtime_builder(tmp_path: Path) -> None:
    env = e14_env(tmp_path)

    receipt_map = json.loads(env.scoreboard[_RECEIPT_PUBLIC])
    assert len(receipt_map) == 1
    (receipt_kid, receipt_public), *_ = receipt_map.items()
    public_raw = _assert_pair_signs(env.gateway[_RECEIPT_PRIVATE], receipt_public)
    assert receipt_kid == hashlib.sha256(public_raw).hexdigest()[:16]

    grant_map = json.loads(env.gateway[_GRANT_PUBLIC])
    assert list(grant_map) == [env.scoreboard[_GRANT_KID]]
    _assert_pair_signs(env.scoreboard[_GRANT_PRIVATE], grant_map[env.scoreboard[_GRANT_KID]])

    # INVARIANT: a private key reaches only the service that signs with it.
    assert _KEY_NAMES & set(env.gateway) == {_RECEIPT_PRIVATE, _GRANT_PUBLIC}
    assert _KEY_NAMES & set(env.scoreboard) == {_RECEIPT_PUBLIC, _GRANT_PRIVATE, _GRANT_KID}


def test_e14_env_archive_dir_is_one_shared_directory(tmp_path: Path) -> None:
    env = e14_env(tmp_path / "runtime-data")

    assert env.archive_dir.is_dir()
    assert env.gateway["AIGW_CACHE_VERSION_ARCHIVE_DIR"] == str(env.archive_dir)
    assert env.scoreboard["SCOREBOARD_ARCHIVE_FS_ROOT"] == str(env.archive_dir)
    assert env.gateway["AIGW_CACHE_VERSIONS_ENABLED"] == "true"
    assert env.scoreboard["SCOREBOARD_CLUSTERING_ENABLED"] == "true"
    assert env.gateway["AIGW_CACHE_VERSION_ARCHIVE_BACKEND"] == "filesystem"
    assert env.scoreboard["SCOREBOARD_ARCHIVE_BACKEND"] == "filesystem"


def test_e14_env_flags_and_archive_dir_are_what_the_wiring_hook_sets(tmp_path: Path) -> None:
    hook_env: dict[str, str] = {}
    apply_local_e14_environment(hook_env, tmp_path)

    env = e14_env(tmp_path)

    # INVARIANT: no harness copy of the hook exists, so the stack env is the hook env.
    assert env.archive_dir == local_archive_dir(tmp_path)
    combined = {**env.gateway, **env.scoreboard}
    assert {name: combined[name] for name in hook_env} == hook_env


def test_e14_env_surfaces_a_failing_wiring_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_hook(environment: MutableMapping[str, str], data_dir: Path) -> None:
        raise RuntimeError("wiring hook broke")

    # WHY: a broken hook must fail every spine, never fall back to a copy of its flags.
    monkeypatch.setattr(e14_env_module, "apply_local_e14_environment", broken_hook)

    with pytest.raises(RuntimeError, match="wiring hook broke"):
        e14_env(tmp_path)


def test_e14_env_refuses_a_key_with_no_service_prefix() -> None:
    with pytest.raises(ValueError) as caught:
        split_env({"OTHER": "secret-value-x"})

    assert "OTHER" in str(caught.value)
    assert "secret-value-x" not in str(caught.value)


def test_e14_env_split_puts_each_prefix_on_its_service() -> None:
    gateway, scoreboard = split_env({"AIGW_A": "1", "AIGATEWAY_B": "2", "SCOREBOARD_C": "3"})

    assert gateway == {"AIGW_A": "1", "AIGATEWAY_B": "2"}
    assert scoreboard == {"SCOREBOARD_C": "3"}


def _recording_edge(user: str) -> tuple[EdgeIdentityTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    return EdgeIdentityTransport(user, inner=httpx.MockTransport(handler)), seen


def test_edge_sets_the_verified_email_and_drops_a_client_copy() -> None:
    edge, seen = _recording_edge("ana@e2e.example")
    body = b'{"score": 1}'
    with httpx.Client(transport=edge, base_url="http://board.test") as client:
        client.post("/v1/scores", content=body, headers={"x-user-email": "mallory@x.example"})
        client.get("/v1/leaderboard/ifeval", headers={"X-USER-EMAIL": "mallory@x.example"})
        client.patch("/v1/scores/1", content=b"{}", headers={"Accept": "application/json"})

    assert [request.headers.get_list("x-user-email") for request in seen] == [
        ["ana@e2e.example"]
    ] * 3
    assert seen[0].content == body
    assert [request.method for request in seen] == ["POST", "GET", "PATCH"]
    assert seen[2].headers["accept"] == "application/json"


def test_edge_close_closes_the_inner_transport() -> None:
    closed: list[bool] = []

    class _Inner(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        def close(self) -> None:
            closed.append(True)

    EdgeIdentityTransport("ana@e2e.example", inner=_Inner()).close()

    assert closed == [True]


def _gateway(tmp_path: Path, extra_env: dict[str, str]) -> CacheSeededGateway:
    return CacheSeededGateway(
        snapshot=tmp_path / "s.gz", manifest=None, work_dir=tmp_path, extra_env=extra_env
    )


@pytest.mark.parametrize("key", ["OPENROUTER_API_KEY", "AIGATEWAY_SECRET_KEY"])
def test_extra_env_refuses_secrets_on_every_child(tmp_path: Path, key: str) -> None:
    expected = f"refusing secret env key: {key}"
    builders = {
        "gateway": lambda: _gateway(tmp_path, {key: "value-x"}),
        "engine": lambda: EngineProcess(work_dir=tmp_path, extra_env={key: "value-x"}),
        "scoreboard": lambda: ScoreboardProcess(work_dir=tmp_path, extra_env={key: "value-x"}),
    }
    for name, build in builders.items():
        with pytest.raises(ValueError) as caught:
            build()
        assert str(caught.value) == expected, name


def test_extra_env_refuses_the_auth_override_on_the_gateway(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as caught:
        _gateway(tmp_path, {"AIGW_AUTH_MODE": "disabled"})

    assert str(caught.value) == "refusing env key: AIGW_AUTH_MODE (use auth_mode=)"


class _FakeContainer:
    username = "board"
    dbname = "board"

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def exec(self, command: list[str]) -> tuple[int, bytes]:
        self.commands.append(command)
        return 0, b"UPDATE 1"


def test_scoreboard_board_prep_always_uses_the_admin_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    routed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        ScoreboardProcess,
        "_set_redistributable_by_route",
        lambda self, base_url, board: routed.append((base_url, board)),
    )
    process = ScoreboardProcess(work_dir=tmp_path)
    container = _FakeContainer()
    process._container = container  # noqa: SLF001 - the Postgres seam, faked

    process._prepare_board("http://board.test", "ifeval")  # noqa: SLF001

    assert routed == [("http://board.test", "ifeval")]
    # INVARIANT: the route is the only path that sets `redistributable`, so SQL never does.
    expected = "UPDATE benchmarks SET case_count = NULL WHERE id = 'ifeval'"
    assert container.commands[0][-1] == expected
