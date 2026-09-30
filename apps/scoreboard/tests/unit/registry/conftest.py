"""Fixtures of the system-registry unit tests.

FEATURE: OME-1307 (E14). The oracles come from the PRD scenarios: names `kevins-best` and
`opus-5.5`, owners `kevin@x.org`, `ana@x.org` and `bruno@y.org`.
"""

from __future__ import annotations

import hashlib

import pytest_asyncio

from scoreboard.core.registry import InvalidUrl4, RegistryService, SystemIdentity
from scoreboard.scores.system_registry_store import TortoiseSystemRepository


def fingerprint_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeFingerprinter:
    """Deterministic SystemFingerprinter: text 'invalid!' raises InvalidUrl4, else sha256(text).

    `calls` records every text it is asked about, so a test can prove it was never reached.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def identify(self, linked_url4: str) -> SystemIdentity:
        self.calls.append(linked_url4)
        if linked_url4 == "invalid!":
            raise InvalidUrl4("not a url4 expression")
        return SystemIdentity(fingerprint=fingerprint_of(linked_url4), candidate_url4=linked_url4)


@pytest_asyncio.fixture
async def fingerprinter() -> FakeFingerprinter:
    return FakeFingerprinter()


@pytest_asyncio.fixture
async def registry(tortoise_db: None, fingerprinter: FakeFingerprinter) -> RegistryService:
    return RegistryService(TortoiseSystemRepository(), fingerprinter)
