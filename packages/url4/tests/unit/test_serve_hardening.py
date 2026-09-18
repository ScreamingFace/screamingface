"""Exposure hardening for `url4 serve` — spec §7 security posture + its config plumbing.

STORY: as an operator I run the node from a compose file where `URL4_HOST` may
interpolate to nothing. That must bind loopback like an unset variable would —
never every interface — because command routes are arbitrary local execution and
the exposure warnings are the only v1 control standing in front of them.

# WHY: these live in their own module rather than appended to test_serve_config.py
# because the append-only gate (run_gates.py) works at FILE level vs HEAD — it
# cannot tell an append from an edit, so appending to a prior suite would force a
# --skip-append-only run and make "were prior tests touched?" unanswerable from
# the gate output. A new file keeps that answer verifiably "no".
"""

from __future__ import annotations

import json

import pytest

import url4.cli.app as cli
from url4.cli._serve import ConfigError, ServeConfig, resolve

CMDS = {"/upper": ("tr", "a-z", "A-Z")}
_FIELDS: tuple[str, ...] = (
    "host",
    "port",
    "default_route",
    "eval_path",
    "concurrency",
    "max_inflight",
    "timeout",
)
# Every serve flag left unset, i.e. what the CLI passes when no flag is given.
_NO_FLAGS: dict[str, object] = {name: None for name in _FIELDS}


def test_empty_env_var_is_unset_not_empty_string() -> None:
    # INVARIANT: an empty env var behaves exactly like an absent one.
    # WHY: `URL4_HOST=` in a .env/compose file is an unresolved interpolation, not a
    # request to bind "". Int fields already rejected "" loudly; string fields silently
    # adopted it, and host="" binds 0.0.0.0 AND :: while reading as "default".
    env = {"URL4_HOST": "", "URL4_PORT": "", "URL4_EVAL_PATH": "", "URL4_DEFAULT_ROUTE": ""}
    config = resolve(_NO_FLAGS, env, None)
    assert config.host == "127.0.0.1"
    assert config.port == 4404
    assert config.eval_path == "/v1"
    assert config.default_route is None


def test_empty_env_var_falls_through_to_the_file_not_straight_to_default(tmp_path) -> None:
    # An empty env var must not short-circuit the ladder: the file still wins over the
    # default. PORTED: the two scalars now live in `server`, which is where
    # url4-node.schema.json puts them.
    path = tmp_path / "url4.json"
    path.write_text(
        json.dumps(
            {"server": {"host": "10.0.0.9", "port": 9}, "routes": {"commands": {"/x": ["cat"]}}}
        ),
        encoding="utf-8",
    )
    config = resolve(_NO_FLAGS, {"URL4_HOST": "", "URL4_PORT": ""}, path)
    assert config.host == "10.0.0.9"
    assert config.port == 9


def test_validate_rejects_empty_host() -> None:
    # INVARIANT: host="" is not loopback — it binds every interface (0.0.0.0 and ::).
    # An operator who wants that writes 0.0.0.0, which trips the exposure warnings.
    with pytest.raises(ConfigError, match="host cannot be empty"):
        ServeConfig(commands=CMDS, host="").validate()


@pytest.mark.parametrize("eval_path", ["", "v1"])
def test_validate_rejects_eval_path_without_leading_slash(eval_path: str) -> None:
    with pytest.raises(ConfigError, match="must start with '/'"):
        ServeConfig(commands=CMDS, eval_path=eval_path).validate()


def test_serve_with_empty_host_flag_is_usage_error(tmp_path, capsys) -> None:
    # The flag path is the vector _pick cannot normalize: `--host ""` is explicit, so
    # validate() is what must reject it. Fail fast (exit 2), never bind.
    config_file = tmp_path / "url4.json"
    config_file.write_text(json.dumps({"routes": {"commands": {"/py": ["cat"]}}}), encoding="utf-8")
    assert cli.main(["serve", "--host", "", "--config", str(config_file)]) == 2
    assert "host cannot be empty" in capsys.readouterr().err


def test_warn_exposure_treats_empty_host_as_exposed(capsys) -> None:
    # AIDEV-NOTE: defense in depth — validate() now rejects host="" before this runs, so
    # this pins the _LOOPBACK set itself: "" is NOT loopback. If a future change relaxes
    # the validate() guard, this test keeps the warnings from silently disappearing.
    cli._warn_exposure(ServeConfig(commands=CMDS, host=""))
    err = capsys.readouterr().err
    assert "WARNING binding non-loopback" in err
    assert "command routes are enabled" in err
