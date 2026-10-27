"""The bounded TOML reader in front of the format-independent definitions.

# FEATURE: hosted BYOM Unit 0 — `AIGW_REMOTE_ENDPOINTS_CONFIG` names a private TOML file read once
# at startup; an explicitly named but unusable file stops startup with a sanitized reason.
# INVARIANT: the reader adds nothing — a TOML file and its in-memory twin give equal definitions and
# grants — and it never reads more than 1 MiB before parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aigateway.plugins.remote_endpoint.definitions import (
    RemoteEndpointConfigError,
    parse_remote_endpoint_config,
)
from aigateway.plugins.remote_endpoint.reader import MAX_CONFIG_BYTES, read_remote_endpoint_config

from .fixtures import (
    ACCOUNT_A,
    ENDPOINT_A,
    ORIGIN_A,
    document,
    endpoint,
    to_toml,
    two_endpoint_document,
)

# The design's own example shape, written by hand rather than by the fixture writer.
_HANDWRITTEN = f"""
schema_version = 1

[[endpoints]]
id = "{ENDPOINT_A}"
display_name = "Research Lab model"
enabled = true
origin = "{ORIGIN_A}"
allowed_account_ids = ["{ACCOUNT_A}"]
validation_target = "model_v1"

[[endpoints.targets]]
alias = "model_v1"
task = "chat"
upstream_model = "researcher/model"
contract = "openai-chat-basic-v1"
request_path = "/v1/chat/completions"
"""


def _write(tmp_path: Path, content: str | bytes) -> Path:
    path = tmp_path / "remote-endpoints.toml"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _refusal(path: Path) -> str:
    with pytest.raises(RemoteEndpointConfigError) as caught:
        read_remote_endpoint_config(path)
    assert caught.value.__cause__ is None
    return str(caught.value)


def test_a_toml_file_and_its_in_memory_twin_give_equal_config(tmp_path: Path) -> None:
    doc = two_endpoint_document()

    from_file = read_remote_endpoint_config(_write(tmp_path, to_toml(doc)))

    assert from_file == parse_remote_endpoint_config(doc)


def test_the_handwritten_design_shape_matches_its_in_memory_twin(tmp_path: Path) -> None:
    twin = document(endpoint(display_name="Research Lab model"))

    assert read_remote_endpoint_config(_write(tmp_path, _HANDWRITTEN)) == (
        parse_remote_endpoint_config(twin)
    )


def test_a_file_of_exactly_the_limit_is_read(tmp_path: Path) -> None:
    body = to_toml(two_endpoint_document()).encode()
    padding = b"#" * (MAX_CONFIG_BYTES - len(body) - 1) + b"\n"

    config = read_remote_endpoint_config(_write(tmp_path, body + padding))

    assert len(config.endpoints) == 2


def test_a_file_over_the_limit_is_refused_before_parsing(tmp_path: Path) -> None:
    oversized = b"#" * MAX_CONFIG_BYTES + b"\n"

    assert "1 MiB" in _refusal(_write(tmp_path, oversized))


def test_a_non_utf8_file_is_refused(tmp_path: Path) -> None:
    assert "UTF-8" in _refusal(_write(tmp_path, b"schema_version = 1\n# \xff\xfe\n"))


def test_invalid_toml_is_refused_without_echoing_content(tmp_path: Path) -> None:
    message = _refusal(_write(tmp_path, 'schema_version = 1\norigin = "https://private.example\n'))

    assert "TOML" in message
    assert "private.example" not in message


def test_an_invalid_document_in_a_valid_file_is_refused_sanitized(tmp_path: Path) -> None:
    doc = document(endpoint(origin="http://private-host.example"))

    message = _refusal(_write(tmp_path, to_toml(doc)))

    assert "endpoints.0.origin" in message
    assert "private-host" not in message


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_an_unreadable_path_is_refused(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "absent.toml" if kind == "missing" else tmp_path

    message = _refusal(path)

    assert "unreadable" in message
    assert str(tmp_path) not in message
