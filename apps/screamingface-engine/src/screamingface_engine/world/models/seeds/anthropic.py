"""anthropic model seeds — mirrors ``aigateway/plugins/anthropic_provider/settings.py``.

Slugs are copied verbatim from that list, so the two can be compared by eye. The canonical
``anthropic/`` prefix is applied by :meth:`ProviderSeed.ids`, never written here.

AIDEV-NOTE: when aigateway's list changes, ``test_declared_models_match_aigateway.py`` fails
until this tuple matches. Add or remove the slug; never edit the guard.
"""

from screamingface_engine.world.models.registry import ProviderSeed

ANTHROPIC = ProviderSeed(
    provider="anthropic",
    slugs=(
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-fable-5",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    ),
)

__all__ = ["ANTHROPIC"]
