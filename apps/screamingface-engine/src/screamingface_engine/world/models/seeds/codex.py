"""codex model seeds — mirrors ``aigateway/plugins/codex_provider/models.py``.

Slugs are copied verbatim from that list, so the two can be compared by eye. The canonical
``codex/`` prefix is applied by :meth:`ProviderSeed.ids`, never written here.

AIDEV-NOTE: when aigateway's list changes, ``test_declared_models_match_aigateway.py`` fails
until this tuple matches. Add or remove the slug; never edit the guard.
"""

from screamingface_engine.world.models.registry import ProviderSeed

CODEX = ProviderSeed(
    provider="codex",
    slugs=(
        "gpt-6-astra",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ),
)

__all__ = ["CODEX"]
