"""04-review-fixes §2.4: url4's error envelope has ONE writer, `world/wire.py`.

# WHY this file exists. The node tier, the forwarder and local mode all answer in url4's error
# dialect. The B2 review found the node tier's 504 reword still building the body by hand, which
# is how three spellings of one wire shape drift apart. These tests pin the one body builder and
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


def test_the_node_tier_builds_no_envelope_by_hand() -> None:
    """The node tier's modules reach the envelope only through `world.wire`."""
    from pathlib import Path

    from screamingface_engine.world import node_tier

    package = Path(node_tier.__file__).parent
    offenders = [path.name for path in package.glob("*.py") if '"error": {' in path.read_text()]

    assert offenders == []
