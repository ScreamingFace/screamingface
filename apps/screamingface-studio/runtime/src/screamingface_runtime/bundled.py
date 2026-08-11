"""Resolve immutable files from source, wheels, and PyInstaller extraction directories."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def runner_config_path() -> Path:
    """Return the URL4 configuration shipped inside this runtime distribution."""

    resource = files("screamingface_runtime.resources").joinpath("url4.toml")
    path = Path(str(resource)).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"bundled URL4 runner config not found: {path}")
    return path


__all__ = ["runner_config_path"]
