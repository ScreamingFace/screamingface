"""build_world gives the model routes and the chat final-step routes one gateway config
(review F5)."""

from __future__ import annotations

import tomllib
from typing import Any

import httpx
import pytest

from screamingface_engine.world import factory
from screamingface_engine.world.config import parse_config
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD


@pytest.mark.asyncio
async def test_final_routes_and_model_routes_share_one_gateway_config(monkeypatch) -> None:
    config = parse_config(
        tomllib.loads('[aigateway]\ndefault_route = "/m"\nmodels = ["m", "prov/a"]\n'),
        {},
        registry=EMPTY_MODEL_WORLD,
    )
    seen: list[object] = []
    original_build = factory.build_aigateway_world
    original_install = factory.install_chat_final

    async def spy_build(cfg: Any, **kwargs: Any) -> Any:
        seen.append(cfg)
        return await original_build(cfg, **kwargs)

    def spy_install(world: Any, cfg: Any) -> None:
        seen.append(cfg)
        original_install(world, cfg)

    monkeypatch.setattr(factory, "build_aigateway_world", spy_build)
    monkeypatch.setattr(factory, "install_chat_final", spy_install)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(500)),
        base_url="http://aigateway.test",
    )
    async with client:
        _node, aclose = await factory.build_world(env={}, config=config, client=client)
        assert aclose is not None
        try:
            assert len(seen) == 2
            assert seen[0] is seen[1]
        finally:
            await aclose()
