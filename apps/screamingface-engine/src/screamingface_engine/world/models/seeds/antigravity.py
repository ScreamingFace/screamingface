"""antigravity model seeds — mirrors ``aigateway/plugins/antigravity_provider/settings.py``.

Slugs are copied verbatim from that list, so the two can be compared by eye. The canonical
``antigravity/`` prefix is applied by :meth:`ProviderSeed.ids`, never written here.

AIDEV-NOTE: when aigateway's list changes, ``test_declared_models_match_aigateway.py`` fails
until this tuple matches. Add or remove the slug; never edit the guard.
"""

from screamingface_engine.world.models.registry import ProviderSeed

ANTIGRAVITY = ProviderSeed(
    provider="antigravity",
    slugs=("gemini-3-flash",),
)

__all__ = ["ANTIGRAVITY"]
