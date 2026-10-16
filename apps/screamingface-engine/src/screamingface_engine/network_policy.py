"""Transport policy shared by catalog and model execution clients."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit


def is_numeric_loopback_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        return (
            parsed.scheme in {"http", "https"}
            and host is not None
            and parsed.username is None
            and parsed.password is None
            and ip_address(host).is_loopback
        )
    except ValueError:
        return False


__all__ = ["is_numeric_loopback_url"]
