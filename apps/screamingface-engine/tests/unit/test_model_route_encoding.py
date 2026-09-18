"""The `:` <-> `~` route-encoding boundary (OME-873).

PORTED FROM url4.json (OME-1183). Most fixtures here were already dicts handed straight to
`parse_config` (TOML only entered through the shared `[aigateway]` key, never through text
parsing), so the only real changes are: the key rename to `world`, one test that wrote a real
`url4.json` file now writes `url4.json`, and one test name that named the old format directly.

FEATURE: OME-873 — the 29 `aigateway_only` ids (colon-bearing) become routable by encoding
their `:` as `~` (already `ROUTE_ID_RE`-legal) wherever a url4 route path is derived, and
decoding back to the real gateway id wherever a real request or comparison against aigateway's
own catalog is made.

STORY: as an SDK user, I can address `huggingface/openai/gpt-oss-120b:cerebras` from a url4
expression by writing its encoded path `/huggingface/openai/gpt-oss-120b~cerebras`, and the
Runner sends aigateway the real, colon-bearing id.
"""

from __future__ import annotations

import json

import pytest

from screamingface_engine import job_env
from screamingface_engine.models.registry import (
    ModelRegistry,
    ProviderSeed,
    decode_route_id,
    encode_route_id,
)
from screamingface_engine.world_config import (
    AigatewaySection,
    WorldConfigError,
    declared_model_ids,
    parse_config,
    routes_for,
)

_REGISTRY = ModelRegistry(
    (
        ProviderSeed("anthropic", ("claude-haiku-4-5",)),
        ProviderSeed("huggingface", ("openai/gpt-oss-120b:cerebras",)),
    )
)
_REAL_ID = "huggingface/openai/gpt-oss-120b:cerebras"
_ROUTE_ID = "huggingface/openai/gpt-oss-120b~cerebras"


def _world(table: dict[str, object], registry: ModelRegistry = _REGISTRY) -> AigatewaySection:
    section = parse_config({"world": table}, {}, registry=registry).aigateway
    assert section is not None
    return section


# --- encode_route_id / decode_route_id: pure functions -----------------------------------


def test_encode_replaces_colon_with_tilde() -> None:
    assert encode_route_id(_REAL_ID) == _ROUTE_ID


def test_decode_replaces_tilde_with_colon() -> None:
    assert decode_route_id(_ROUTE_ID) == _REAL_ID


def test_encode_is_the_identity_on_an_id_with_no_colon() -> None:
    assert encode_route_id("anthropic/claude-haiku-4-5") == "anthropic/claude-haiku-4-5"


def test_decode_is_the_identity_on_an_id_with_no_tilde() -> None:
    assert decode_route_id("anthropic/claude-haiku-4-5") == "anthropic/claude-haiku-4-5"


def test_encode_then_decode_round_trips() -> None:
    assert decode_route_id(encode_route_id(_REAL_ID)) == _REAL_ID


@pytest.mark.parametrize(
    "model_id", ["huggingface/org/model:novita", "openrouter/liquid/lfm-2.5-2.6b:free"]
)
def test_encode_round_trips_every_shape_of_colon_id(model_id: str) -> None:
    assert decode_route_id(encode_route_id(model_id)) == model_id


# --- registry construction reserves '~' for the colon-escape ------------------------------


def test_a_slug_containing_a_literal_tilde_is_refused() -> None:
    # INVARIANT: '~' is reserved exclusively as the colon-escape (OME-873). A future seed that
    # legitimately needs one would silently collide with an encoded aigateway_only route.
    with pytest.raises(ValueError, match="reserved"):
        ModelRegistry((ProviderSeed("openrouter", ("openai/gpt-5.5~preview",)),))


# --- world_config: an aigateway_only id now enters the world, under its encoded id ---------


def test_an_aigateway_only_id_enters_the_world_under_its_encoded_id() -> None:
    section = _world({"default_route": "/anthropic/claude-haiku-4-5"})

    ids = {m.id for m in section.models}
    assert _ROUTE_ID in ids
    assert _REAL_ID not in ids  # the real (colon) id never appears as a route id


def test_routes_for_derives_a_route_id_path_with_no_further_encoding() -> None:
    section = _world({"default_route": "/anthropic/claude-haiku-4-5"})

    routes = routes_for(section.models)

    assert "/" + _ROUTE_ID in routes


def test_a_world_entry_overrides_an_aigateway_only_id_by_its_encoded_form() -> None:
    # PORTED, renamed from `test_a_toml_entry_overrides_...` — the fixture below is a
    # `world.models` entry, not a TOML array-of-tables entry, but its meaning is unchanged.
    section = _world(
        {
            "default_route": "/anthropic/claude-haiku-4-5",
            "models": [{"id": _ROUTE_ID, "web_search": False}],
        }
    )

    specs = {m.id: m for m in section.models}
    assert len(specs) == 2  # the override REPLACES, it does not duplicate
    assert specs[_ROUTE_ID].web_search is False


def test_declared_model_ids_reports_the_real_gateway_id(tmp_path) -> None:
    # WHY: this is what gets compared against aigateway's own `GET /v1/models` response, whose
    # `id` field is always the real (colon-bearing) id — never the url4-route form.
    config = tmp_path / "url4.json"
    config.write_text(json.dumps({"world": {"default_route": "/anthropic/claude-haiku-4-5"}}))

    ids = declared_model_ids({job_env.RUNNER_CONFIG: str(config)}, registry=_REGISTRY)

    assert _REAL_ID in ids
    assert _ROUTE_ID not in ids


def test_a_literal_colon_in_default_route_gets_a_specific_error() -> None:
    with pytest.raises(WorldConfigError, match="cannot be a route"):
        _world({"default_route": "/" + _REAL_ID})
