"""The one direct-mount filter that the App and the local stack share (chat-run CR-S19).

FEATURE: chat-run. `direct_mount_descriptors` lists the mounts of a node that are direct mounts,
so an internal route of a gateway world is never public on either shape.
"""

from __future__ import annotations

import tomllib

import httpx
import pytest

from screamingface_engine.world.chat_turn import CHAT_TURN_ROUTE
from screamingface_engine.world.config import parse_config
from screamingface_engine.world.factory import build_world, direct_mount_paths
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.serving import direct_mount_descriptors
from url4.peer.server import Url4Node

_AIGATEWAY = """
[aigateway]
base_url = "http://aigateway.test"
default_route = "/m"
models = ["m"]
"""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        base_url="http://aigateway.test",
    )


@pytest.mark.asyncio
async def test_direct_mount_descriptors_lists_only_direct_mounts() -> None:
    config = parse_config(tomllib.loads(_AIGATEWAY), {}, registry=EMPTY_MODEL_WORLD)
    async with _client() as client:
        node, aclose = await build_world(env={}, config=config, client=client)
        assert aclose is not None
        try:
            assert isinstance(node, Url4Node)
            assert CHAT_TURN_ROUTE in node.processor_routes()

            paths = [mount.path for mount in direct_mount_descriptors(node)]

            assert paths
            assert not [p for p in paths if p.startswith("/ensemble/")]
            assert CHAT_TURN_ROUTE not in paths
            assert set(paths) <= direct_mount_paths(node)
        finally:
            await aclose()


def test_a_node_that_is_not_a_url4_node_has_no_direct_mounts() -> None:
    assert direct_mount_descriptors(object()) == ()
