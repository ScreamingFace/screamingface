"""Bounded caller-reported version tokens from Engine run evidence (OME-416)."""

import re

_VERSION = re.compile(r"[A-Za-z0-9._+-]{1,128}", re.ASCII)


def valid_client_version(value: object) -> str | None:
    """Match the Engine's diagnostic token contract without claiming a release."""
    return value if isinstance(value, str) and _VERSION.fullmatch(value) else None


def client_version(value: object) -> str | None:
    if value is None:
        return None
    selected = valid_client_version(value)
    if selected is None:
        raise ValueError("Candidate client_version must be a bounded ASCII version token or None")
    return selected
