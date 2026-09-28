"""04-review-fixes §2.4: url4's error envelope has ONE writer, `world/wire.py`.

# WHY this file exists. The App's mount routes and local mode both answer in url4's error
# dialect. The B2 review found a 504 reword still building the body by hand, which is how two
# spellings of one wire shape drift apart. These tests pin the one body builder and
# that the ASGI writer uses it byte for byte.
"""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from typing import Any

import pytest

from screamingface_engine.world import wire


def test_the_envelope_body_is_url4s_error_shape() -> None:
    body = wire.url4_error_body("timeout", "too slow")

    assert json.loads(body) == {"error": {"code": "timeout", "message": "too slow"}}


@pytest.mark.asyncio
async def test_send_url4_error_writes_exactly_that_body() -> None:
    sent: list[MutableMapping[str, Any]] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    await wire.send_url4_error(send, 503, "upstream_unavailable", "down", retry_after=1)

    assert sent[0]["status"] == 503
    assert (b"retry-after", b"1") in sent[0]["headers"]
    assert sent[1]["body"] == wire.url4_error_body("upstream_unavailable", "down")


def test_the_mount_surfaces_build_no_envelope_by_hand() -> None:
    """The mount routes and local mode reach the envelope only through `world.wire`: no dict
    literal with an ``"error"`` key appears in their code."""
    import ast
    from pathlib import Path

    import screamingface_engine

    root = Path(screamingface_engine.__file__).parent
    offenders = [
        f"{relative}:{node.lineno}"
        for relative in ("rest/mounts.py", "local.py")
        for node in ast.walk(ast.parse((root / relative).read_text()))
        if isinstance(node, ast.Dict)
        and any(isinstance(k, ast.Constant) and k.value == "error" for k in node.keys)
    ]

    assert offenders == []
