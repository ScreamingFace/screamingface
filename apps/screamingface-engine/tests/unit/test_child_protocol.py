"""The worker ⇄ warm-child hand-off protocol (uniform executor PRD 03, contracts.md C5).

Child → worker, on the control pipe: `READY {"pid":<int>,"world":"ok"|"error"}\\n`, then `ACK\\n`.
Worker → child, on stdin: one RUN_SPEC JSON line (≤ 1 MiB).
"""

import json

import pytest

from screamingface_engine import child_protocol as cp
from screamingface_engine import job_env
from screamingface_engine.runner_queue import decode_message, encode_message


def test_ready_line_round_trips() -> None:
    line = cp.encode_ready(pid=4242, world_ok=False)
    assert line.endswith(b"\n")
    assert cp.decode_ready(line) == cp.Ready(pid=4242, world_ok=False)
    assert cp.decode_ready(cp.encode_ready(pid=7, world_ok=True)).world_ok


@pytest.mark.parametrize("line", [b"", b"ACK\n", b"READY not-json\n", b'READY {"pid":"x"}\n'])
def test_a_malformed_ready_line_is_refused(line: bytes) -> None:
    with pytest.raises(cp.ProtocolError):
        cp.decode_ready(line)


def test_ack_is_one_line() -> None:
    assert cp.ACK == b"ACK\n"


def test_spec_env_equals_message_env_codec() -> None:
    """WRM-2: RUN_SPEC.env is the RUN_MESSAGE body as decoded — ONE codec serves both, so the
    child reads the same keys with the same meaning as the worker did."""
    message = encode_message("t-1", "(gpt,claude)!'hi'", 60, identity={"X-User-Email": "a@x"})
    decoded = decode_message(message)
    spec = cp.decode_spec(cp.encode_spec(decoded, io_concurrency=3))
    assert spec.env == decoded
    assert spec.io_concurrency == 3


def test_spec_is_one_json_line_with_the_spec_version() -> None:
    line = cp.encode_spec({job_env.TOPIC: "t"}, io_concurrency=1)
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    assert json.loads(line)["spec_version"] == cp.SPEC_VERSION == "2"


def test_bad_spec_oversized_is_refused() -> None:
    """WRM-15 (size)."""
    huge = b'{"spec_version":"2","env":{"k":"' + b"x" * cp.MAX_SPEC_BYTES + b'"}}\n'
    with pytest.raises(cp.SpecError) as exc:
        cp.decode_spec(huge)
    assert exc.value.code == "spec_too_large"


@pytest.mark.parametrize(
    "line",
    [b"not json\n", b"[]\n", b'{"spec_version":"2"}\n', b'{"spec_version":"2","env":{"k":1}}\n'],
)
def test_bad_spec_malformed_is_refused(line: bytes) -> None:
    """WRM-15 (JSON / shape)."""
    with pytest.raises(cp.SpecError) as exc:
        cp.decode_spec(line)
    assert exc.value.code == "spec_malformed"


def test_bad_spec_unknown_major_version_is_refused() -> None:
    """WRM-15 (version) / erd.md §2: an unknown major version is refused with its own code."""
    line = b'{"spec_version":"3","env":{},"io_concurrency":1}\n'
    with pytest.raises(cp.SpecError) as exc:
        cp.decode_spec(line)
    assert exc.value.code == "unsupported_spec_version"


def test_the_protocol_module_imports_only_the_stdlib() -> None:
    """C14: both halves import it, so it must not pull either half in."""
    import ast
    import sys
    from pathlib import Path

    tree = ast.parse(Path(cp.__file__).read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    roots.discard("__future__")
    assert roots <= sys.stdlib_module_names


def test_a_refusal_carries_its_code() -> None:
    assert cp.refused_code(cp.encode_refused("unsupported_spec_version")) == (
        "unsupported_spec_version"
    )
    assert cp.refused_code(cp.ACK) is None
