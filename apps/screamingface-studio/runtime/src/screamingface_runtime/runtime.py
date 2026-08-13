"""Compatibility wrapper around the shared ScreamingFace local runtime."""

from __future__ import annotations

from screamingface._runtime.config import RuntimeConfig
from screamingface._runtime.server import run

__all__ = ["RuntimeConfig", "run"]
