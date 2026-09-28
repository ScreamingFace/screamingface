"""Bounded caller-reported software identity, kept only in ordinary run evidence."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator

from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import LogData

CLIENT_VERSION_ENV = "URL4_CLOUD_CLIENT_VERSION"
VERSION_ATTRIBUTE = "screamingface.client.version"
_VERSION = re.compile(r"[A-Za-z0-9._+-]{1,128}", re.ASCII)


def valid_version(value: str | None) -> str | None:
    """Validate a diagnostic token without normalizing it into a claimed release."""
    return value if value is not None and _VERSION.fullmatch(value) else None


def parse_user_agent(value: str | None) -> str | None:
    """Extract one unambiguous product token; unusable headers never block execution."""
    if not value or len(value) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        return None
    # WHY reject comments: a product name inside a UA comment is not a product assertion.
    if "(" in value or ")" in value:
        return None
    versions = [
        token.removeprefix("screamingface/")
        for token in value.split()
        if token.startswith("screamingface/")
    ]
    return valid_version(versions[0]) if len(versions) == 1 else None


class ProvenanceExecutor(Executor):
    """Prepend one log step; lifecycle owns its sequencing, trace, and stream retention."""

    def __init__(self, inner: Executor, client_version: str | None) -> None:
        self._inner = inner
        self._version = valid_version(client_version)

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncGenerator[ExecStep]:
        if self._version is not None:
            # INVARIANT: a wire log only, never a Python log or exported span attribute.
            yield LogData.at("INFO", "Client software version", {VERSION_ATTRIBUTE: self._version})
        steps = self._inner.execute(url4, trace=trace)
        try:
            async for step in steps:
                yield step
        finally:
            close = getattr(steps, "aclose", None)
            if close is not None:
                await close()
