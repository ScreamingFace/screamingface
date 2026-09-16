"""Declared model ids must be valid URL4 expression paths before the world starts.

PORTED FROM url4.json (OME-1183). `_config`'s dict fixture only needed the `aigateway` -> `world`
key rename. The one test that read the real repo file (`apps/screamingface-engine/url4.json`,
via `job_env.RUNNER_CONFIG`) now points at this directory's `url4.json` instead — in the real
migration this would point at the renamed repo file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.models.registry import EMPTY_MODEL_WORLD, decode_route_id
from screamingface_engine.world_config import (
    WorldConfigError,
    declared_model_ids,
    load_config,
    parse_config,
)


def _config(model: str) -> dict[str, object]:
    return {
        "world": {
            "default_route": model,
            "models": [{"id": model}],
        }
    }


def test_colon_qualified_model_id_is_rejected_at_config_parse() -> None:
    model = "huggingface/google/gemma-2-2b-it:featherless-ai"

    with pytest.raises(WorldConfigError, match="URL4 expression path"):
        parse_config(_config(model), {}, registry=EMPTY_MODEL_WORLD)


def test_expression_path_compatible_model_id_remains_declared() -> None:
    model = "openrouter/openai/gpt-5.5"

    section = parse_config(_config(model), {}, registry=EMPTY_MODEL_WORLD).aigateway

    assert section is not None
    assert [item.id for item in section.models] == [model]


def test_control_plane_and_runner_read_the_same_declared_ids() -> None:
    config_path = Path(__file__).resolve().parents[2] / "url4.json"
    env = {job_env.RUNNER_CONFIG: str(config_path)}

    section = load_config(env).aigateway

    assert section is not None
    # OME-873: `declared_model_ids` reports the REAL gateway id (what aigateway's own catalog
    # names), while `section.models[*].id` is the url4-ROUTE form — decode to compare like for
    # like. The two are still one invariant: same world, two projections of the same ids.
    assert declared_model_ids(env) == frozenset(decode_route_id(item.id) for item in section.models)
