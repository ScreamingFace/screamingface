"""Shared Engine-origin classification for Client surfaces and evidence."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit


def _is_hosted_engine(engine_url: str) -> bool:
    """Return whether an Engine URL points beyond the local machine."""

    hostname = urlsplit(engine_url).hostname
    if hostname == "localhost":
        return False
    try:
        address = ip_address(hostname or "")
    except ValueError:
        return True
    return not (address.is_loopback or address.is_unspecified)


def _is_screamingface_engine(engine_url: str) -> bool:
    """Return whether the URL belongs to ScreamingFace's hosted Engine family."""

    # INVARIANT: only ScreamingFace's own hosted Engine earns the brand name + 😱 mark;
    # any other remote Engine renders a neutral "Hosted Engine".
    host = (urlsplit(engine_url).hostname or "").lower()
    return host == "screamingface.ai" or host.endswith(".screamingface.ai")


__all__: list[str] = []
