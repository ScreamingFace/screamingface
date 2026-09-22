"""The per-run world-shape log keeps its pre-F1 logger name (prd/01 AC1).

The "runner world topic=…" INFO line predates F1 and was emitted on logger
`screamingface_engine.runner.main`. F1 moved the emitter into `world/factory.py`; a logger-name
change is an observable change on the ensemble path (log routing keyed on the name), and prd/01
AC1's bar is byte-for-byte parity. This test pins the name so a future rename of the module —
or a switch back to `__name__` — fails here instead of silently re-routing the line.
"""

from __future__ import annotations

import logging
import tomllib

import httpx
import pytest

from screamingface_engine.world.config import WorldConfig, parse_config
from screamingface_engine.world.factory import build_world
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD

_AIGATEWAY = """
[aigateway]
default_route = "/m"
models = ["m"]
"""


def _config() -> WorldConfig:
    return parse_config(tomllib.loads(_AIGATEWAY), {}, registry=EMPTY_MODEL_WORLD)


@pytest.mark.asyncio
async def test_the_per_run_world_shape_line_keeps_its_runner_logger_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="screamingface_engine.runner.main"):
        async with httpx.AsyncClient() as client:
            io, aclose = await build_world(env={}, config=_config(), client=client)
        try:
            records = [r for r in caplog.records if r.message.startswith("runner world topic=")]
            assert records, "the per-run world-shape line must fire during build_world"
            assert records[0].name == "screamingface_engine.runner.main"
        finally:
            if aclose is not None:
                await aclose()
    assert io is not None
