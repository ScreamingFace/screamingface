"""The declared model registry — canonicalisation, validation, and the colon partition."""

from __future__ import annotations

import pytest

from screamingface_engine.world.models.registry import (
    EMPTY_MODEL_WORLD,
    ModelRegistry,
    ProviderSeed,
    is_route_legal,
)


def test_a_bare_slug_is_canonicalised_with_its_provider_prefix() -> None:
    registry = ModelRegistry((ProviderSeed("anthropic", ("claude-opus-5",)),))

    assert registry.routable == frozenset({"anthropic/claude-opus-5"})


def test_an_already_qualified_slug_is_left_untouched() -> None:
    # INVARIANT: prefixing is idempotent. Without this every OpenRouter id would gain a
    # second prefix (`openrouter/openrouter/openai/...`) — the OME-795 failure class.
    registry = ModelRegistry(
        (ProviderSeed("openrouter", ("openrouter/openai/gpt-5.5", "openai/gpt-5.4")),)
    )

    assert registry.routable == frozenset(
        {"openrouter/openai/gpt-5.5", "openrouter/openai/gpt-5.4"}
    )


def test_the_same_id_from_two_seeds_is_refused() -> None:
    seeds = (
        ProviderSeed("anthropic", ("claude-opus-5",)),
        ProviderSeed("anthropic", ("anthropic/claude-opus-5",)),
    )

    with pytest.raises(ValueError, match="duplicate model id"):
        ModelRegistry(seeds)


def test_a_colon_bearing_id_is_partitioned_rather_than_refused() -> None:
    # INVARIANT: a `:` is illegal in a url4 path segment (spec §8), so these ids can never be
    # routes. They are still declared, so the guard can assert set equality against aigateway
    # and OME-819 has a precise work-list.
    registry = ModelRegistry(
        (ProviderSeed("huggingface", ("openai/gpt-oss-120b:cerebras", "openai/gpt-oss-20b")),)
    )

    assert registry.aigateway_only == frozenset({"huggingface/openai/gpt-oss-120b:cerebras"})
    assert registry.routable == frozenset({"huggingface/openai/gpt-oss-20b"})


def test_all_ids_is_the_union_of_both_partitions() -> None:
    registry = ModelRegistry((ProviderSeed("huggingface", ("org/a:novita", "org/b")),))

    assert registry.all_ids == registry.routable | registry.aigateway_only
    assert len(registry) == 2


@pytest.mark.parametrize("slug", ["has space", "has%percent", "has#hash", "has?query"])
def test_an_id_illegal_for_a_reason_other_than_a_colon_is_refused(slug: str) -> None:
    # WHY raise rather than partition: a colon is a KNOWN, tracked grammar limit with real ids
    # behind it. Any other illegal character is a typo, and silently filing it under
    # `aigateway_only` would hide it from the equality guard forever.
    with pytest.raises(ValueError, match="not a valid URL4 expression path"):
        ModelRegistry((ProviderSeed("openrouter", (slug,)),))


def test_an_empty_slug_is_refused() -> None:
    with pytest.raises(ValueError, match="empty model id"):
        ModelRegistry((ProviderSeed("openrouter", ("",)),))


def test_a_slug_may_not_start_with_a_slash() -> None:
    with pytest.raises(ValueError, match="must not start with '/'"):
        ModelRegistry((ProviderSeed("openrouter", ("/openai/gpt-5.5",)),))


def test_the_empty_world_is_a_valid_registry() -> None:
    assert len(EMPTY_MODEL_WORLD) == 0
    assert EMPTY_MODEL_WORLD.all_ids == frozenset()


def test_route_legality_is_a_pure_function_of_the_id() -> None:
    assert is_route_legal("openrouter/openai/gpt-5.5")
    assert is_route_legal("claude-haiku-4-5")
    assert not is_route_legal("huggingface/org/model:novita")
