"""gemini-cli model seeds — mirrors ``aigateway/plugins/gemini_provider/models.py``.

Slugs are copied verbatim from that list, so the two can be compared by eye. The canonical
``gemini-cli/`` prefix is applied by :meth:`ProviderSeed.ids`, never written here.

AIDEV-NOTE: when aigateway's list changes, ``test_declared_models_match_aigateway.py`` fails
until this tuple matches. Add or remove the slug; never edit the guard.
"""

from screamingface_engine.world.models.registry import ProviderSeed

GEMINI_CLI = ProviderSeed(
    provider="gemini-cli",
    slugs=(
        "gemini-3.1-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ),
)

__all__ = ["GEMINI_CLI"]
