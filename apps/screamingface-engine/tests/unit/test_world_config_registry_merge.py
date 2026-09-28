"""The declared world is the registry, with url4.toml layered additively on top."""

from __future__ import annotations

import pytest

from screamingface_engine.world.config import (
    AigatewaySection,
    WorldConfigError,
    parse_config,
    routes_for,
)
from screamingface_engine.world.models.registry import (
    EMPTY_MODEL_WORLD,
    ModelRegistry,
    ProviderSeed,
)

_REGISTRY = ModelRegistry(
    (
        ProviderSeed("anthropic", ("claude-haiku-4-5", "claude-opus-5")),
        ProviderSeed("huggingface", ("org/model:novita",)),
    )
)


def _world(table: dict[str, object], registry: ModelRegistry = _REGISTRY) -> AigatewaySection:
    section = parse_config({"aigateway": table}, {}, registry=registry).aigateway
    assert section is not None
    return section


def test_registry_ids_reach_the_declared_world_without_any_toml_entry() -> None:
    section = _world({"default_route": "/anthropic/claude-haiku-4-5"})

    # OME-873: the aigateway_only seed ("org/model:novita") reaches the world too, under its
    # `~`-encoded route id — see test_an_aigateway_only_id_enters_the_world_under_its_encoded_id.
    assert {m.id for m in section.models} == {
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-opus-5",
        "huggingface/org/model~novita",
    }


def test_a_toml_entry_may_add_an_id_the_registry_lacks() -> None:
    # WHY additive: ollama discovers its models at run time and two provider seed lists are
    # env-overridable, so a deployment must still be able to declare its own routes.
    section = _world(
        {
            "default_route": "/anthropic/claude-haiku-4-5",
            "models": [{"id": "ollama/llama-4"}],
        }
    )

    assert "ollama/llama-4" in {m.id for m in section.models}


def test_a_toml_entry_overrides_the_registry_capability_for_that_id() -> None:
    section = _world(
        {
            "default_route": "/anthropic/claude-haiku-4-5",
            "models": [{"id": "anthropic/claude-opus-5", "web_search": False}],
        }
    )

    specs = {m.id: m for m in section.models}
    assert specs["anthropic/claude-opus-5"].web_search is False
    assert specs["anthropic/claude-haiku-4-5"].web_search is True


def test_a_toml_entry_duplicating_a_registry_id_yields_exactly_one_spec() -> None:
    # INVARIANT: routes_for maps "/" + id, so two specs for one id would collapse silently and
    # whichever lost would take its capability with it.
    section = _world(
        {
            "default_route": "/anthropic/claude-haiku-4-5",
            "models": [{"id": "anthropic/claude-opus-5", "web_search": False}],
        }
    )

    ids = [m.id for m in section.models]
    assert ids.count("anthropic/claude-opus-5") == 1
    assert len(routes_for(section.models)) == len(ids)


def test_an_aigateway_only_id_enters_the_world_under_its_encoded_id() -> None:
    # OME-873 supersedes this test's old name/claim ("never enters the world"): the real,
    # colon-bearing id still never appears as a route id — see
    # test_declared_model_ids_reports_the_real_gateway_id in test_model_route_encoding.py — but
    # the model itself IS now addressable, under its `~`-encoded form.
    section = _world({"default_route": "/anthropic/claude-haiku-4-5"})

    ids = {m.id for m in section.models}
    assert "huggingface/org/model~novita" in ids
    assert "huggingface/org/model:novita" not in ids


def test_a_default_route_declared_only_by_the_registry_validates() -> None:
    # INVARIANT: the OME-795 failure mode — a default_route no model matched failed inside a
    # user's expression rather than at boot.
    section = _world({"default_route": "/anthropic/claude-opus-5"})

    assert section.default_model == "anthropic/claude-opus-5"


def test_a_default_route_naming_an_aigateway_only_id_is_refused() -> None:
    with pytest.raises(WorldConfigError, match="cannot be a route"):
        _world({"default_route": "/huggingface/org/model:novita"})


def test_a_toml_only_world_still_builds_against_the_empty_registry() -> None:
    # Backward compatibility for a deployment pointing URL4_RUNNER_CONFIG at its own file.
    section = _world(
        {"default_route": "/ollama/llama-4", "models": [{"id": "ollama/llama-4"}]},
        EMPTY_MODEL_WORLD,
    )

    assert {m.id for m in section.models} == {"ollama/llama-4"}


def test_a_world_that_would_declare_nothing_is_refused() -> None:
    with pytest.raises(WorldConfigError, match="at least one model"):
        _world({"default_route": "/x"}, EMPTY_MODEL_WORLD)
