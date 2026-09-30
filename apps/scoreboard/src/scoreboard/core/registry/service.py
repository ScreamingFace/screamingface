"""RegistryService — resolves a submission's url4 to a system revision (erd.md §2.3, PRD §3.1).

FEATURE: OME-1307 (E14). INVARIANT: no parameter of any method is a fingerprint; it is always
recomputed from the url4 text (SR-1).
"""

from __future__ import annotations

from .errors import (
    NotSystemOwner,
    PinNotFound,
    RegistryConflict,
    RegistryWriteConflict,
    SystemNameTaken,
    SystemNotFound,
    Url4TooLarge,
)
from .model import (
    BoardVisibility,
    DatePin,
    NamePin,
    Resolution,
    RevisionPin,
    RevisionRef,
    SystemAlreadyNamed,
    SystemIdentity,
)
from .names import normalize_system_name, suggest_name
from .pins import parse_pin
from .ports import SystemFingerprinter, SystemRepository

MAX_URL4_CHARS = 32_000  # D7 X-22: the existing ScoreSubmission cap (scores/schemas.py:378), 422
_ATTEMPTS = (1, 2)


class RegistryService:
    def __init__(self, repository: SystemRepository, fingerprinter: SystemFingerprinter) -> None:
        self._repository = repository
        self._fingerprinter = fingerprinter

    async def resolve_for_submit(
        self,
        linked_url4: str,
        requested_name: str,
        revision_of: str | None,
        submitter: str,
        board_visibility: BoardVisibility,
        *,
        connection: object | None = None,
    ) -> Resolution:
        identity = self.identify(linked_url4)
        if board_visibility == "private":
            # INVARIANT (SR-11, I-N4): a private board never touches the registry.
            return Resolution("private", identity, None, None, None)
        # OD-R2: `revision_of` names the system; `requested_name` is not read when it is given.
        name = normalize_system_name(revision_of if revision_of is not None else requested_name)
        conflict: RegistryWriteConflict | None = None
        for _ in _ATTEMPTS:
            known = await self._repository.find_revision_by_fingerprint(
                identity.fingerprint, connection=connection
            )
            if known is not None:
                # INVARIANT (I-N2, OD-R3): a known fingerprint always wins, also with `revision_of`.
                return _existing(identity, known, name)
            try:
                return await self._write(name, revision_of, identity, submitter, connection)
            except RegistryWriteConflict as exc:
                # WHY one retry: the loser re-reads by fingerprint, then by name, and so lands on
                # the winner's row (SR-D2, SR-D3, SR-D4). A second loss means heavy contention.
                conflict = exc
        raise RegistryConflict("the registry write lost a race twice") from conflict

    async def resolve_pin(
        self, pin: str, *, connection: object | None = None
    ) -> RevisionRef | list[RevisionRef]:
        parsed = parse_pin(pin)
        system = await self._repository.find_system_by_name(parsed.name, connection=connection)
        if system is None:
            raise PinNotFound(pin)
        revisions = await self._repository.list_revisions(system.id, connection=connection)
        return _select_revisions(pin, parsed, revisions)

    def identify(self, linked_url4: str) -> SystemIdentity:
        size = len(linked_url4)  # characters, like `max_length` in scores/schemas.py:378
        # WHY the service keeps its own cap when the route already has one (D7 X-22): the
        # backfill and any later caller do not go through `ScoreSubmission`. Both caps are the
        # same number and the same unit, so the client sees one rule.
        if size > MAX_URL4_CHARS:
            raise Url4TooLarge(size, MAX_URL4_CHARS)
        return self._fingerprinter.identify(linked_url4)

    def fingerprint(self, linked_url4: str) -> str:
        return self.identify(linked_url4).fingerprint

    async def _write(
        self,
        name: str,
        revision_of: str | None,
        identity: SystemIdentity,
        submitter: str,
        connection: object | None,
    ) -> Resolution:
        if revision_of is not None:
            return await self._declare_revision(name, identity, submitter, connection)
        return await self._claim(name, identity, submitter, connection)

    async def _claim(
        self, name: str, identity: SystemIdentity, submitter: str, connection: object | None
    ) -> Resolution:
        if await self._repository.find_system_by_name(name, connection=connection) is not None:
            # SR-E3, also when the owner is the submitter: the owner must use `revision_of`.
            raise SystemNameTaken(name, suggest_name(name, identity.fingerprint))
        revision = await self._repository.create_system_with_first_revision(
            name=name, owner=submitter, identity=identity, connection=connection
        )
        return Resolution("new", identity, revision.system, revision, None)

    async def _declare_revision(
        self, name: str, identity: SystemIdentity, submitter: str, connection: object | None
    ) -> Resolution:
        system = await self._repository.find_system_by_name(name, connection=connection)
        if system is None:
            raise SystemNotFound(name)
        if system.owner != submitter:
            # INVARIANT (SR-E1): checked before any write.
            raise NotSystemOwner(name)
        revision = await self._repository.create_next_revision(
            system=system, identity=identity, declared_by=submitter, connection=connection
        )
        return Resolution("revision", identity, revision.system, revision, None)


def _existing(identity: SystemIdentity, known: RevisionRef, name: str) -> Resolution:
    if known.system.name == name:
        return Resolution("existing", identity, known.system, known, None)
    notice = SystemAlreadyNamed(known.system.name, known.system.owner)
    return Resolution("renamed_notice", identity, known.system, known, notice)


def _select_revisions(
    pin: str, parsed: NamePin | RevisionPin | DatePin, revisions: list[RevisionRef]
) -> RevisionRef | list[RevisionRef]:
    if isinstance(parsed, DatePin):
        # SB-grants picks the result by date (PRD SR-H5); the registry hands over all revisions.
        return revisions
    if isinstance(parsed, NamePin):
        if not revisions:
            raise PinNotFound(pin)
        return revisions[-1]
    for revision in revisions:
        if revision.revision == parsed.revision:
            return revision
    raise PinNotFound(pin)
