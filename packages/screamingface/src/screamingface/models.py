"""Model discovery through the lazy default Client."""

from __future__ import annotations

from collections.abc import Sequence

from screamingface._default_client import default_client
from screamingface.discovery import ModelDetails, ModelInfo


def list() -> Sequence[ModelInfo]:
    """List Models currently addressable through the configured SF Engine."""

    return default_client().models.list()


def get(model_id: str) -> ModelDetails:
    """Get profile-specific parameters and capabilities for one Model."""

    return default_client().models.get(model_id)


__all__ = ["get", "list"]
