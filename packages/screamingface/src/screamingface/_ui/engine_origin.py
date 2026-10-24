"""Shared Engine-origin classification for notebook UI surfaces."""

from __future__ import annotations

from urllib.parse import urlsplit

from screamingface._core.engine_origin import is_hosted_engine as _is_hosted_engine  # noqa: F401


def _is_screamingface_engine(engine_url: str) -> bool:
    """Return whether the URL belongs to ScreamingFace's hosted Engine family."""

    # INVARIANT: only ScreamingFace's own hosted Engine earns the brand name + 😱 mark;
    # any other remote Engine renders a neutral "Hosted Engine".
    host = (urlsplit(engine_url).hostname or "").lower()
    return host == "screamingface.ai" or host.endswith(".screamingface.ai")


__all__: list[str] = []
