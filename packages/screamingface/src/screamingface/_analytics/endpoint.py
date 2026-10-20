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
    # Validate malformed ports before any optional analytics network request.
    _ = parsed.port
    return value
