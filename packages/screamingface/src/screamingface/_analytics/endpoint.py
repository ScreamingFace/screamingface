"""One destination for the lifetime of the process, shared by both transports."""

import os
from functools import lru_cache
from urllib.parse import urlsplit


@lru_cache(maxsize=1)
def analytics_origin() -> str:
    value = (
        os.environ.get("SCREAMINGFACE_ANALYTICS_ENDPOINT", "https://analytics.screamingface.ai")
        .strip()
        .rstrip("/")
    )
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in value
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in value)
    ):
        raise ValueError("SCREAMINGFACE_ANALYTICS_ENDPOINT must be an HTTPS origin")
    # Match browser origin serialization: lowercase hosts and omit default ports.
    port = parsed.port
    host = parsed.hostname.encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{host}]"
    suffix = f":{port}" if port is not None and port != 443 else ""
    return f"https://{host}{suffix}"
