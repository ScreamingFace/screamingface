"""The shipped `url4.toml` gives one model call 30 minutes (OME-1616).

# FEATURE: long-running evaluations (ARC-AGI-2) — one model call may run up to 30 minutes.
# INVARIANT: the Engine sends `timeout_s` to the gateway as `x-aigw-execution-timeout-s`, and the
# gateway takes the smaller of that header and its own cap, so the Engine's budget is a ceiling on
# every call no matter how the gateway is configured. The file is baked into the Runner image and
# has no environment override.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from screamingface_engine.world.config import parse_config

SHIPPED = Path(__file__).resolve().parents[2] / "url4.toml"
THIRTY_MINUTES = 1800.0


def test_the_shipped_world_gives_a_model_call_thirty_minutes() -> None:
    world = parse_config(tomllib.loads(SHIPPED.read_text()), {})

    assert world.aigateway is not None
    assert world.aigateway.timeout_s == THIRTY_MINUTES
    # WHY: admission defaults to the execution budget; a stray override would cut the wait short.
    assert world.aigateway.queue_timeout_s is None
