"""Shared local/remote engine classification; no network or presentation dependencies."""

from ipaddress import ip_address
from urllib.parse import urlsplit


def is_hosted_engine(engine_url: str) -> bool:
    hostname = urlsplit(engine_url).hostname
    if hostname == "localhost":
        return False
    try:
        address = ip_address(hostname or "")
    except ValueError:
        return True
    return not (address.is_loopback or address.is_unspecified)
