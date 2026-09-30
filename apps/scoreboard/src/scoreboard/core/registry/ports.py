"""Ports of the system registry (hexagonal core: the core defines them, adapters implement them).

FEATURE: OME-1307 (E14).

INVARIANT: `SystemRegistry` is the inbound port (SB-submit and SB-grants call it);
`SystemRepository` and `SystemFingerprinter` are the outbound ports.
INVARIANT: no parameter of any port is a fingerprint supplied by a client (SR-1).
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .model import BoardVisibility, Resolution, RevisionRef, SystemIdentity, SystemRef


class SystemFingerprinter(Protocol):
    def identify(self, linked_url4: str) -> SystemIdentity:
        """Raise InvalidUrl4 when the text is not a url4 expression."""
        ...


# `connection` is typed `object | None` so the core stays free of Tortoise. The adapter casts
# it to `BaseDBAsyncClient`. None means "the default connection".
class SystemRepository(Protocol):
    async def find_revision_by_fingerprint(
        self, fingerprint: str, *, connection: object | None = None
    ) -> RevisionRef | None: ...

    async def find_system_by_name(
        self, name: str, *, connection: object | None = None
    ) -> SystemRef | None: ...

    async def create_system_with_first_revision(
        self, *, name: str, owner: str, identity: SystemIdentity, connection: object | None = None
    ) -> RevisionRef:
        """Raise RegistryWriteConflict when a unique constraint rejects the write."""
        ...

    async def create_next_revision(
        self,
        *,
        system: SystemRef,
        identity: SystemIdentity,
        declared_by: str,
        connection: object | None = None,
    ) -> RevisionRef:
        """Raise RegistryWriteConflict when a unique constraint rejects the write."""
        ...

    async def list_revisions(
        self, system_id: UUID, *, connection: object | None = None
    ) -> list[RevisionRef]:
        """By revision ASC."""
        ...


class SystemRegistry(Protocol):
    # The three operations of PRD §3.1, with the PRD parameter names and order.
    async def resolve_for_submit(
        self,
        linked_url4: str,
        requested_name: str,  # SB-submit passes the submission's spec_id
        revision_of: str | None,
        submitter: str,  # the verified cloudflare_headers identity (D5); never None
        board_visibility: BoardVisibility,
        *,
        connection: object | None = None,
    ) -> Resolution: ...

    async def resolve_pin(
        self, pin: str, *, connection: object | None = None
    ) -> RevisionRef | list[RevisionRef]: ...

    def fingerprint(self, linked_url4: str) -> str:
        """Pure: identify(...).fingerprint."""
        ...
