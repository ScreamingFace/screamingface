"""LR-1 .. LR-6 — `screamingface up` turns the E14 flags on and wires one archive dir.

FEATURE: OME-1307 (E14) D6, STORY: as a researcher, I run `screamingface up` and a traced run is
captured, frozen and archived with no setup. INVARIANT under test: the gateway writer and the
scoreboard reader name ONE directory (contracts C8, local mode), an operator value always wins, and
the archive holds full prompts and answers, so it is private (0700).
"""

from __future__ import annotations

import ast
import asyncio
import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from screamingface._runtime import server
from screamingface._runtime.config import RuntimeConfig
from screamingface._runtime.local_features import (
    ARCHIVE_ENV_GROUP,
    LOCAL_E14_FLAGS,
    apply_local_e14_environment,
)

KEY_ENV = (
    "AIGATEWAY_RECEIPT_SIGNING_KEY",
    "SCOREBOARD_RECEIPT_PUBLIC_KEYS",
    "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY",
    "SCOREBOARD_REPLAY_GRANT_SIGNING_KID",
    "AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS",
)
E14_ENV = (*LOCAL_E14_FLAGS, *ARCHIVE_ENV_GROUP)
WRITER_DIR = "AIGW_CACHE_VERSION_ARCHIVE_DIR"
READER_DIR = "SCOREBOARD_ARCHIVE_FS_ROOT"


def test_empty_env_gets_flags_and_one_private_archive_dir(tmp_path: Path) -> None:
    environment: dict[str, str] = {}

    apply_local_e14_environment(environment, tmp_path)

    assert {name: environment[name] for name in LOCAL_E14_FLAGS} == {
        "AIGW_CACHE_VERSIONS_ENABLED": "true",
        "SCOREBOARD_CLUSTERING_ENABLED": "true",
    }
    assert environment["AIGW_CACHE_VERSION_ARCHIVE_BACKEND"] == "filesystem"
    assert environment["SCOREBOARD_ARCHIVE_BACKEND"] == "filesystem"
    archive = tmp_path / "cache-version-archive"
    assert environment[WRITER_DIR] == environment[READER_DIR] == str(archive)
    assert archive.is_dir()
    assert stat.S_IMODE(archive.stat().st_mode) == 0o700
    # WHY: the live request cache is a separate user choice (OME-1169); capture works with it off.
    assert "AIGW_REQUEST_CACHE_ENABLED" not in environment


def test_an_existing_archive_dir_is_made_private(tmp_path: Path) -> None:
    archive = tmp_path / "cache-version-archive"
    archive.mkdir(mode=0o755)
    archive.chmod(0o755)

    apply_local_e14_environment({}, tmp_path)

    assert stat.S_IMODE(archive.stat().st_mode) == 0o700


def test_operator_values_win(tmp_path: Path) -> None:
    flag_off = {"AIGW_CACHE_VERSIONS_ENABLED": "false"}

    apply_local_e14_environment(flag_off, tmp_path / "flag-case")

    assert flag_off["AIGW_CACHE_VERSIONS_ENABLED"] == "false"
    assert flag_off["SCOREBOARD_CLUSTERING_ENABLED"] == "true"
    shared = str(tmp_path / "operator-dir")
    group = {
        "AIGW_CACHE_VERSION_ARCHIVE_BACKEND": "filesystem",
        WRITER_DIR: shared,
        "SCOREBOARD_ARCHIVE_BACKEND": "filesystem",
        READER_DIR: shared,
    }
    environment = dict(group)

    apply_local_e14_environment(environment, tmp_path)

    assert {name: environment[name] for name in group} == group
    assert not (tmp_path / "cache-version-archive").exists()


def test_partial_archive_group_fails(tmp_path: Path) -> None:
    environment = {WRITER_DIR: str(tmp_path)}

    with pytest.raises(RuntimeError, match="set all of") as caught:
        apply_local_e14_environment(environment, tmp_path)

    assert all(name in str(caught.value) for name in ARCHIVE_ENV_GROUP)
    assert "or none of them" in str(caught.value)
    # INVARIANT: a refused start half-applies nothing.
    assert environment == {WRITER_DIR: str(tmp_path)}


def test_two_filesystem_dirs_must_be_one(tmp_path: Path) -> None:
    environment = {
        "AIGW_CACHE_VERSION_ARCHIVE_BACKEND": "filesystem",
        WRITER_DIR: str(tmp_path / "writer"),
        "SCOREBOARD_ARCHIVE_BACKEND": "filesystem",
        READER_DIR: str(tmp_path / "reader"),
    }

    with pytest.raises(RuntimeError, match="one directory") as caught:
        apply_local_e14_environment(environment, tmp_path)

    assert "C8" in str(caught.value)


def test_s3_group_with_two_dirs_is_not_a_local_split(tmp_path: Path) -> None:
    # WHY: the "one directory" rule applies only when both backends are `filesystem`.
    environment = {
        "AIGW_CACHE_VERSION_ARCHIVE_BACKEND": "s3",
        WRITER_DIR: str(tmp_path / "writer"),
        "SCOREBOARD_ARCHIVE_BACKEND": "s3",
        READER_DIR: str(tmp_path / "reader"),
    }

    apply_local_e14_environment(environment, tmp_path)

    assert environment[WRITER_DIR] != environment[READER_DIR]


class _Stop(Exception):
    pass


class _Source:
    def describe(self) -> str:
        return "test source"


def _run_up_until_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RuntimeConfig, dict[str, str]]:
    """Run `server.run` up to `_build_apps`; return the config and a copy of `os.environ` there."""
    # WHY set-then-delete: `monkeypatch` only restores a name it saw, and `run` sets these names on
    # the real `os.environ`. The setenv makes the teardown remove them again.
    for name in (*KEY_ENV, *E14_ENV):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    seen: dict[str, str] = {}

    async def migrate(config: RuntimeConfig) -> None:
        # INVARIANT: the flags and the archive are in place before ANY service step.
        assert set(E14_ENV) <= set(os.environ)

    def build_apps(config: RuntimeConfig) -> Any:
        seen.update(os.environ)
        raise _Stop

    monkeypatch.setattr(server, "require_runtime_extra", lambda: _Source())
    monkeypatch.setattr(server, "_migrate", migrate)
    monkeypatch.setattr(server, "_build_apps", build_apps)
    runner = tmp_path / "url4.toml"
    runner.write_text("")
    config = RuntimeConfig(data_dir=tmp_path / "data", runner_config=runner)
    with pytest.raises(_Stop):
        asyncio.run(server.run(config))
    return config, seen


def test_up_sets_flags_archive_and_keys_before_the_apps_are_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, seen = _run_up_until_apps(tmp_path, monkeypatch)

    assert all(seen[name] == "true" for name in LOCAL_E14_FLAGS)
    assert set(E14_ENV) <= set(seen)
    assert set(KEY_ENV) <= set(seen)
    archive = config.data_dir / "cache-version-archive"
    assert archive.is_dir()
    assert seen[WRITER_DIR] == seen[READER_DIR] == str(archive)
    receipt_map = json.loads(seen["SCOREBOARD_RECEIPT_PUBLIC_KEYS"])
    (kid,) = receipt_map
    assert kid == hashlib.sha256(base64.b64decode(receipt_map[kid])).hexdigest()[:16]
    printed = capsys.readouterr().out
    assert seen["AIGATEWAY_RECEIPT_SIGNING_KEY"] not in printed
    assert seen["SCOREBOARD_REPLAY_GRANT_SIGNING_KEY"] not in printed


_FORBIDDEN_PREFIXES = (
    "cache_versions_enabled",
    "clustering_enabled",
    "receipt_signing_key",
    "receipt_public_keys",
    "replay_grant_",
    "cache_version_archive_",
    "archive_",
)


def test_local_settings_constructors_leave_e14_fields_to_the_env() -> None:
    """The two `Settings(...)` calls of `server.py` read the E14 fields from the environment.

    INVARIANT: a keyword here would beat the operator's variable, and the hook would not matter.
    """
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    checked = 0
    for function in ast.walk(tree):
        if not (
            isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            and function.name in {"_build_apps", "run_scoreboard"}
        ):
            continue
        for call in ast.walk(function):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id in {"Settings", "GatewaySettings"}
            ):
                checked += 1
                names = [keyword.arg or "" for keyword in call.keywords]
                assert not [n for n in names if n.startswith(_FORBIDDEN_PREFIXES)], names
    assert checked >= 2
