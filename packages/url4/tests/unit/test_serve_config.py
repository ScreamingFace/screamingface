"""ServeConfig resolution + validation for `url4 serve` (url4._serve).

STORY: as an operator I define my backends entirely as `routes.commands` — user-owned
argv templates; an LLM backend is my own gateway script mounted as a command — and
configure the node via flags, URL4_* env, and url4.json. Flags win, then env, then the
file, then defaults; unusable settings fail fast before the server binds, not mid-request.

PORTED FROM url4.json (OME-1183). Three edits and no more: the fixture helper writes
JSON, scalars move into their catalog group, and every argv is an array.
"""

from __future__ import annotations

import json

import pytest

from url4.cli._serve import ConfigError, ServeConfig, resolve

CMDS = {"/upper": ("tr", "a-z", "A-Z"), "/echo": ("cat",)}


def _write(tmp_path, payload: dict, name: str = "url4.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_defaults_when_only_commands_supplied(tmp_path) -> None:
    config = resolve(
        {}, {}, _write(tmp_path, {"routes": {"commands": {"/upper": ["tr", "a-z", "A-Z"]}}})
    )
    assert config.host == "127.0.0.1"
    assert config.port == 4404
    assert config.default_route is None  # unset — resolves to the first command
    assert config.resolved_default_route == "/upper"
    assert config.commands["/upper"] == ("tr", "a-z", "A-Z")


def test_connector_surface_is_gone() -> None:
    # INVARIANT: the aigateway connector was removed — the serve config carries
    # NO route map and no backend url/token; commands are the only backends.
    fields = ServeConfig.__dataclass_fields__
    for legacy in ("routes", "backend_url", "backend_token", "processor"):
        assert legacy not in fields, legacy


def test_flag_beats_env_beats_file(tmp_path) -> None:
    path = _write(tmp_path, {"server": {"host": "file-host", "port": 1}})
    env = {"URL4_HOST": "env-host", "URL4_PORT": "2"}
    config = resolve({"host": "flag-host", "port": None}, env, path)
    assert config.host == "flag-host"  # flag wins
    assert config.port == 2  # no flag -> env wins over the file


def test_scalars_are_read_from_their_catalog_group(tmp_path) -> None:
    """The flat->nested move. `limits` and `server` are separate groups in
    url4-node.schema.json, and resolution reads each field from its own."""
    path = _write(tmp_path, {"server": {"port": 9}, "limits": {"timeout": 3.5, "concurrency": 4}})
    config = resolve({}, {}, path)
    assert (config.port, config.timeout, config.concurrency) == (9, 3.5, 4)


def test_a_top_level_scalar_is_no_longer_honoured(tmp_path) -> None:
    """The TOML spelling must stop working. Silently honouring it would leave a
    half-converted file running and hide the migration from whoever wrote it."""
    config = resolve(
        {}, {}, _write(tmp_path, {"port": 1234, "routes": {"commands": {"/x": ["cat"]}}})
    )
    assert config.port == 4404  # the default, not 1234


def test_absent_group_is_an_unset_field_not_an_error(tmp_path) -> None:
    """A url4.json need not declare `limits` at all to run on the defaults."""
    config = resolve({}, {}, _write(tmp_path, {"routes": {"commands": {"/x": ["cat"]}}}))
    assert config.timeout == 120.0
    assert config.concurrency == 32


def test_group_of_the_wrong_type_is_rejected(tmp_path) -> None:
    with pytest.raises(ConfigError, match="'limits' must be an object"):
        resolve({}, {}, _write(tmp_path, {"limits": 5}))


def test_default_route_precedence_flag_env_file(tmp_path) -> None:
    path = _write(
        tmp_path,
        {
            "routes": {
                "default_route": "/file",
                "commands": {"/file": ["cat"], "/env": ["cat"], "/flag": ["cat"]},
            }
        },
    )
    assert resolve({}, {}, path).default_route == "/file"
    assert resolve({}, {"URL4_DEFAULT_ROUTE": "/env"}, path).default_route == "/env"
    config = resolve({"default_route": "/flag"}, {"URL4_DEFAULT_ROUTE": "/env"}, path)
    assert config.default_route == "/flag"
    assert config.resolved_default_route == "/flag"


def test_env_typed_coercion_and_bad_value() -> None:
    assert resolve({}, {"URL4_CONCURRENCY": "7"}, None).concurrency == 7
    with pytest.raises(ConfigError, match="concurrency must be an integer"):
        resolve({}, {"URL4_CONCURRENCY": "not-an-int"}, None)


def test_bad_float_and_command_type(tmp_path) -> None:
    with pytest.raises(ConfigError, match="timeout must be a number"):
        resolve({"timeout": "not-a-number"}, {}, None)
    path = _write(tmp_path, {"routes": {"commands": {"/x": 5}}}, name="c.json")
    with pytest.raises(ConfigError, match="command must be an array of strings, got number"):
        resolve({}, {}, path)


def test_argv_string_form_is_rejected_with_the_fix_in_the_message(tmp_path) -> None:
    """THE BREAKING CHANGE. TOML accepted `"/py" = "python3 -"` and shlex.split it.
    An argv is now an array — and the error hands over the exact array to paste,
    because that is the whole of the fix."""
    path = _write(tmp_path, {"routes": {"commands": {"/py": "python3 -"}}})
    with pytest.raises(ConfigError) as exc:
        resolve({}, {}, path)
    assert '["python3", "-"]' in str(exc.value)


def test_commands_are_arrays(tmp_path) -> None:
    path = _write(
        tmp_path, {"routes": {"commands": {"/py": ["python3", "-"], "/sh": ["bash", "-c", "cat"]}}}
    )
    config = resolve({}, {}, path)
    assert config.commands["/py"] == ("python3", "-")
    assert config.commands["/sh"] == ("bash", "-c", "cat")


def test_first_declared_command_is_the_default_route(tmp_path) -> None:
    # Declaration order is the tie-breaker the operator controls. JSON objects keep
    # insertion order through `json.load`, exactly as TOML tables did — so this
    # operator-visible behaviour survives the migration unchanged.
    path = _write(tmp_path, {"routes": {"commands": {"/py": ["python3", "-"], "/sh": ["cat"]}}})
    assert resolve({}, {}, path).resolved_default_route == "/py"


def test_unreadable_file_is_config_error(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{this = = broken", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot read config"):
        resolve({}, {}, path)


def test_top_level_array_is_rejected_in_json_vocabulary(tmp_path) -> None:
    path = tmp_path / "url4.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a JSON object, got array"):
        resolve({}, {}, path)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"commands": CMDS, "concurrency": 0}, "concurrency must be >= 1"),
        ({"commands": CMDS, "max_inflight": 0}, "max-inflight must be >= 1"),
        ({"commands": CMDS, "timeout": 0.0}, "timeout must be > 0"),
        ({"commands": {"noslash": ("cat",)}}, "must start with '/'"),
        ({"commands": CMDS, "default_route": "/absent"}, "not a declared command route"),
        ({}, "requires at least one"),
        ({"default_route": "/x"}, "requires at least one"),
    ],
)
def test_validate_rejects(kwargs, match) -> None:
    with pytest.raises(ConfigError, match=match):
        ServeConfig(**kwargs).validate()


def test_validate_rejects_reserved_path_and_empty_argv() -> None:
    with pytest.raises(ConfigError, match="reserved"):
        ServeConfig(commands={"/echo": ("cat",), "/healthz": ("cat",)}).validate()
    with pytest.raises(ConfigError, match="empty argv"):
        ServeConfig(commands={"/py": ()}).validate()


def test_validate_rejects_eval_path_on_reserved_health_path() -> None:
    config = ServeConfig(commands=CMDS, eval_path="/healthz")
    with pytest.raises(ConfigError, match="reserved health path"):
        config.validate()


def test_valid_config_passes() -> None:
    config = ServeConfig(commands=CMDS)
    config.validate()
    assert config.resolved_default_route == "/upper"  # first declared command
