"""Tortoise implementation of the SystemRepository port (E14, OME-1307).

FEATURE: OME-1307 (E14) — persistence of `System` and `SystemRevision`.

INVARIANT: a non-None `connection` must be the transaction that the current task opened with
`in_transaction()`. Tortoise binds that transaction to the task context, so the nested
`in_transaction()` of a write becomes a SAVEPOINT on the same transaction. When `connection` is
None, a write opens its own top-level transaction (the backfill command and the unit tests).
INVARIANT: the adapter never returns a Tortoise object; every row is mapped to a frozen `*Ref`.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from tortoise import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from scoreboard.core.registry import (
    RegistryWriteConflict,
    RevisionRef,
    SystemIdentity,
    SystemRef,
)

from .models import System, SystemRevision


def _db(connection: object | None) -> BaseDBAsyncClient | None:
    return cast(BaseDBAsyncClient | None, connection)


def _system_ref(row: System) -> SystemRef:
    return SystemRef(id=row.id, name=row.name, owner=row.owner)


def _revision_ref(row: SystemRevision, system: SystemRef) -> RevisionRef:
    return RevisionRef(
        id=row.id,
        system=system,
        revision=row.revision,
        fingerprint=row.fingerprint,
        candidate_url4=row.candidate_url4,
        created_at=row.created_at,
    )


class TortoiseSystemRepository:
    async def find_revision_by_fingerprint(
        self, fingerprint: str, *, connection: object | None = None
    ) -> RevisionRef | None:
        row = (
            await SystemRevision.filter(fingerprint=fingerprint)
            .select_related("system")
            .using_db(_db(connection))
            .first()
        )
        return None if row is None else _revision_ref(row, _system_ref(row.system))

    async def find_system_by_name(
        self, name: str, *, connection: object | None = None
    ) -> SystemRef | None:
        row = await System.filter(name=name).using_db(_db(connection)).first()
        return None if row is None else _system_ref(row)

    async def create_system_with_first_revision(
        self, *, name: str, owner: str, identity: SystemIdentity, connection: object | None = None
    ) -> RevisionRef:
        # WHY the `try` is OUTSIDE the savepoint: on PostgreSQL a failed statement aborts the
        # whole transaction until a `ROLLBACK TO SAVEPOINT`. The nested context does that rollback
        # on exit, so the caller's outer transaction stays usable and, under READ COMMITTED, the
        # next read sees the winner's committed row. Do not catch the error inside the block.
        try:
            async with in_transaction() as savepoint:
                system = await System.create(using_db=savepoint, name=name, owner=owner)
                revision = await SystemRevision.create(
                    using_db=savepoint,
                    system=system,
                    revision=1,
                    fingerprint=identity.fingerprint,
                    candidate_url4=identity.candidate_url4,
                    declared_by=owner,
                )
        except IntegrityError as exc:
            raise RegistryWriteConflict(str(exc)) from exc
        return _revision_ref(revision, _system_ref(system))

    async def create_next_revision(
        self,
        *,
        system: SystemRef,
        identity: SystemIdentity,
        declared_by: str,
        connection: object | None = None,
    ) -> RevisionRef:
        try:
            async with in_transaction() as savepoint:
                number = await self._next_revision_number(savepoint, system.id)
                revision = await SystemRevision.create(
                    using_db=savepoint,
                    system_id=system.id,
                    revision=number,
                    fingerprint=identity.fingerprint,
                    candidate_url4=identity.candidate_url4,
                    declared_by=declared_by,
                )
        except IntegrityError as exc:
            raise RegistryWriteConflict(str(exc)) from exc
        return _revision_ref(revision, system)

    async def list_revisions(
        self, system_id: UUID, *, connection: object | None = None
    ) -> list[RevisionRef]:
        rows = (
            await SystemRevision.filter(system_id=system_id)
            .select_related("system")
            .order_by("revision")
            .using_db(_db(connection))
        )
        return [_revision_ref(row, _system_ref(row.system)) for row in rows]

    async def _next_revision_number(self, connection: BaseDBAsyncClient, system_id: UUID) -> int:
        latest = (
            await SystemRevision.filter(system_id=system_id)
            .order_by("-revision")
            .using_db(connection)
            .first()
        )
        return 1 if latest is None else latest.revision + 1
