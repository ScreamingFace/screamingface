"""RegistryService against the Tortoise adapter and a fake fingerprinter.

FEATURE: OME-1307 (E14). Ids: SR-1, SR-6..SR-11, SR-12 (SQLite half), SR-13, SR-18, SR-19,
SR-20 (resolve half), SR-H3-SB (service half). Oracles come from the PRD scenarios.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from scoreboard.adapters.url4_fingerprinter import Url4Fingerprinter
from scoreboard.config import Settings
from scoreboard.core.registry import (
    InvalidPin,
    InvalidSystemName,
    InvalidUrl4,
    NotSystemOwner,
    PinNotFound,
    RegistryConflict,
    RegistryService,
    RegistryWriteConflict,
    RevisionRef,
    SystemAlreadyNamed,
    SystemNameTaken,
    SystemNotFound,
    SystemRepository,
    Url4TooLarge,
)
from scoreboard.main import create_app
from scoreboard.scores.models import System, SystemRevision
from scoreboard.scores.system_registry_store import TortoiseSystemRepository
from tests.unit.registry.conftest import FakeFingerprinter, fingerprint_of
from tests.unit.registry.test_url4_fingerprinter import _vectors

KEVIN = "kevin@x.org"
ANA = "ana@x.org"
BRUNO = "bruno@y.org"


async def _counts() -> tuple[int, int]:
    return await System.all().count(), await SystemRevision.all().count()


async def _submit(
    registry: RegistryService,
    text: str,
    name: str,
    submitter: str,
    *,
    revision_of: str | None = None,
):
    return await registry.resolve_for_submit(text, name, revision_of, submitter, "public")


def test_sr1_no_parameter_of_resolve_for_submit_is_a_fingerprint() -> None:
    names = list(inspect.signature(RegistryService.resolve_for_submit).parameters)

    assert [name for name in names if "fingerprint" in name] == []


@pytest.mark.asyncio
async def test_sr1_fingerprint_ignores_client_supplied_value(registry: RegistryService) -> None:
    await _submit(registry, "U_A", "ana-system", ANA)

    resolution = await _submit(registry, "U_B", "kevins-best", KEVIN)

    assert resolution.outcome == "new"
    assert resolution.revision is not None
    assert resolution.revision.fingerprint == fingerprint_of("U_B")
    ana = await System.get(name="ana-system")
    assert ana.owner == ANA
    assert await SystemRevision.filter(system_id=ana.id).count() == 1


@pytest.mark.asyncio
async def test_sr6_new_fingerprint_new_name_creates_system_rev1(registry: RegistryService) -> None:
    resolution = await _submit(registry, "U_K", "kevins-best", KEVIN)

    assert resolution.outcome == "new"
    assert resolution.notice is None
    system = await System.get(name="kevins-best")
    assert system.owner == KEVIN
    revision = await SystemRevision.get(fingerprint=fingerprint_of("U_K"))
    assert revision.revision == 1
    assert revision.declared_by == KEVIN
    assert revision.candidate_url4 == "U_K"
    assert resolution.identity.fingerprint == fingerprint_of("U_K")
    assert resolution.revision is not None and resolution.system is not None
    assert resolution.revision.id == revision.id
    assert resolution.system == resolution.revision.system
    assert resolution.system.name == "kevins-best" and resolution.system.owner == KEVIN


@pytest.mark.asyncio
async def test_sr6_the_requested_name_is_normalized(registry: RegistryService) -> None:
    resolution = await _submit(registry, "U_K", "Kevins-Best", KEVIN)

    assert resolution.system is not None and resolution.system.name == "kevins-best"


@pytest.mark.asyncio
async def test_sr7_known_fingerprint_reuses_name_no_rows(registry: RegistryService) -> None:
    first = await _submit(registry, "U_O", "opus-5.5", ANA)
    before = await _counts()

    second = await _submit(registry, "U_O", "opus-5.5", BRUNO)

    assert second.outcome == "existing"
    assert second.notice is None
    assert first.revision is not None and second.revision is not None
    assert second.revision.id == first.revision.id
    assert await _counts() == before


@pytest.mark.asyncio
async def test_sr8_known_fingerprint_other_name_returns_notice(registry: RegistryService) -> None:
    await _submit(registry, "U_O", "opus-5.5", ANA)
    before = await _counts()

    resolution = await _submit(registry, "U_O", "bruno-opus", BRUNO)

    assert resolution.outcome == "renamed_notice"
    assert resolution.notice == SystemAlreadyNamed("opus-5.5", ANA)
    assert resolution.system is not None and resolution.system.name == "opus-5.5"
    assert await _counts() == before


@pytest.mark.asyncio
async def test_sr9_owner_declares_revision_two(registry: RegistryService) -> None:
    await _submit(registry, "U_1", "kevins-best", KEVIN)

    resolution = await _submit(registry, "U_2", "ignored", KEVIN, revision_of="kevins-best")

    assert resolution.outcome == "revision"
    assert resolution.revision is not None and resolution.revision.revision == 2
    assert resolution.system is not None and resolution.system.name == "kevins-best"
    row = await SystemRevision.get(fingerprint=fingerprint_of("U_2"))
    assert row.revision == 2 and row.declared_by == KEVIN
    assert await System.all().count() == 1


@pytest.mark.asyncio
async def test_sr9_revision_of_names_the_system_and_requested_name_is_not_read(
    registry: RegistryService,
) -> None:
    await _submit(registry, "U_1", "kevins-best", KEVIN)

    # OD-R2: `requested_name` here would fail the name rules, and it must not be read.
    resolution = await _submit(registry, "a/b", "a/b", KEVIN, revision_of="Kevins-Best")

    assert resolution.outcome == "revision"
    assert resolution.system is not None and resolution.system.name == "kevins-best"


@pytest.mark.asyncio
async def test_sr10_non_owner_revision_rejected_403_no_write(registry: RegistryService) -> None:
    await _submit(registry, "U_1", "kevins-best", KEVIN)
    before = await _counts()

    with pytest.raises(NotSystemOwner) as info:
        await _submit(registry, "U_2", "kevins-best", BRUNO, revision_of="kevins-best")

    assert info.value.code == "not_system_owner"
    assert await _counts() == before


class _SpyRepository:
    """A SystemRepository whose every method fails the test: the private path never calls it."""

    def __getattr__(self, name: str):
        raise AssertionError(f"the repository was called: {name}")


@pytest.mark.asyncio
async def test_sr11_private_board_never_writes_registry() -> None:
    service = RegistryService(cast(SystemRepository, _SpyRepository()), FakeFingerprinter())

    resolution = await service.resolve_for_submit("U_P", "secret", None, KEVIN, "private")

    assert resolution.outcome == "private"
    assert resolution.system is None and resolution.revision is None
    assert resolution.notice is None
    assert resolution.identity.fingerprint == fingerprint_of("U_P")


@pytest.mark.asyncio
async def test_sr11_private_board_still_rejects_a_bad_url4_and_reads_no_name() -> None:
    service = RegistryService(cast(SystemRepository, _SpyRepository()), FakeFingerprinter())

    with pytest.raises(InvalidUrl4):
        await service.resolve_for_submit("invalid!", "secret", None, KEVIN, "private")
    # A name that would fail the name rules is not read on a private board (no registry name).
    resolution = await service.resolve_for_submit("U_P", "a/b", None, KEVIN, "private")
    assert resolution.outcome == "private"


@pytest.mark.asyncio
async def test_sr13_taken_name_by_other_system_409_with_suggestion(
    registry: RegistryService,
) -> None:
    await _submit(registry, "U_1", "opus-5.5", ANA)
    before = await _counts()

    with pytest.raises(SystemNameTaken) as info:
        await _submit(registry, "U_2", "opus-5.5", BRUNO)

    assert info.value.code == "system_name_taken"
    assert info.value.suggestion == f"opus-5.5-{fingerprint_of('U_2')[:4]}"
    assert await _counts() == before


@pytest.mark.asyncio
async def test_sr13_the_owner_must_use_revision_of_for_a_new_fingerprint(
    registry: RegistryService,
) -> None:
    await _submit(registry, "U_1", "opus-5.5", ANA)

    with pytest.raises(SystemNameTaken):
        await _submit(registry, "U_2", "opus-5.5", ANA)


@pytest.mark.asyncio
async def test_sr18_revision_of_unknown_404(registry: RegistryService) -> None:
    with pytest.raises(SystemNotFound) as info:
        await _submit(registry, "U_1", "x", KEVIN, revision_of="nope")

    assert info.value.code == "system_not_found"
    assert await _counts() == (0, 0)


@pytest.mark.asyncio
async def test_i_n2_a_known_fingerprint_with_revision_of_creates_no_second_revision(
    registry: RegistryService,
) -> None:
    await _submit(registry, "U_1", "kevins-best", KEVIN)
    before = await _counts()

    same = await _submit(registry, "U_1", "x", KEVIN, revision_of="kevins-best")
    other = await _submit(registry, "U_1", "x", BRUNO, revision_of="kevins-best")

    assert same.outcome == "existing"
    # A known fingerprint wins, also for a non-owner: no write happens, so no ownership is at stake.
    assert other.outcome == "existing"
    assert await _counts() == before


@pytest.mark.asyncio
async def test_od_r3_a_known_fingerprint_with_revision_of_another_system_returns_a_notice(
    registry: RegistryService,
) -> None:
    await _submit(registry, "U_1", "kevins-best", KEVIN)
    await _submit(registry, "U_2", "other", ANA)

    resolution = await _submit(registry, "U_1", "x", ANA, revision_of="other")

    assert resolution.outcome == "renamed_notice"
    assert resolution.notice == SystemAlreadyNamed("kevins-best", KEVIN)


@pytest.mark.parametrize("name", ["", "a/b", "a" * 65, "-x"])
@pytest.mark.asyncio
async def test_od_r1_an_invalid_name_fails_even_for_a_known_fingerprint(
    registry: RegistryService, name: str
) -> None:
    await _submit(registry, "U_1", "kevins-best", KEVIN)

    with pytest.raises(InvalidSystemName):
        await _submit(registry, "U_1", name, BRUNO)


@pytest.mark.asyncio
async def test_sr19_unparseable_url4_422_and_oversize_422(
    registry: RegistryService, fingerprinter: FakeFingerprinter
) -> None:
    with pytest.raises(InvalidUrl4) as bad:
        await _submit(registry, "invalid!", "x", KEVIN)
    assert bad.value.code == "invalid_url4"
    fingerprinter.calls.clear()

    with pytest.raises(Url4TooLarge) as big:
        await _submit(registry, "a" * 32_001, "x", KEVIN)

    assert big.value.code == "url4_too_large"
    assert (big.value.size, big.value.limit) == (32_001, 32_000)
    # INVARIANT: the size check runs before the fingerprinter.
    assert fingerprinter.calls == []
    assert await _counts() == (0, 0)


@pytest.mark.parametrize("text", ["a" * 32_000, "é" * 32_000])
@pytest.mark.asyncio
async def test_sr19_the_cap_counts_characters_not_bytes(
    registry: RegistryService, text: str
) -> None:
    identity = registry.identify(text)

    assert identity.fingerprint == fingerprint_of(text)
    assert registry.fingerprint(text) == identity.fingerprint


@pytest.mark.asyncio
async def test_the_pure_fingerprint_operation_raises_like_identify(
    registry: RegistryService,
) -> None:
    with pytest.raises(Url4TooLarge):
        registry.fingerprint("a" * 32_001)
    with pytest.raises(InvalidUrl4):
        registry.fingerprint("invalid!")


async def _seed_two_revisions(registry: RegistryService) -> None:
    await _submit(registry, "U_1", "kevins-best", KEVIN)
    await _submit(registry, "U_2", "x", KEVIN, revision_of="kevins-best")


@pytest.mark.asyncio
async def test_sr20_resolve_pin_forms(registry: RegistryService) -> None:
    await _seed_two_revisions(registry)

    by_name = await registry.resolve_pin("kevins-best")
    by_revision = await registry.resolve_pin("kevins-best@r1")
    by_date = await registry.resolve_pin("kevins-best@2999-01-01")

    assert isinstance(by_name, RevisionRef) and by_name.revision == 2
    assert isinstance(by_revision, RevisionRef) and by_revision.revision == 1
    assert isinstance(by_date, list)
    assert [revision.revision for revision in by_date] == [1, 2]


@pytest.mark.asyncio
async def test_sr20_a_pin_is_resolved_case_insensitively_on_the_name(
    registry: RegistryService,
) -> None:
    await _seed_two_revisions(registry)

    pin = await registry.resolve_pin("Kevins-Best@r2")

    assert isinstance(pin, RevisionRef) and pin.revision == 2


@pytest.mark.asyncio
async def test_sr20_a_pin_with_the_date_form_returns_every_revision_to_the_caller(
    registry: RegistryService,
) -> None:
    await _seed_two_revisions(registry)

    pins = await registry.resolve_pin("kevins-best@2026-09-01T10:00:00+02:00")

    assert isinstance(pins, list) and len(pins) == 2


@pytest.mark.parametrize("pin", ["kevins-best@r3", "nope", "nope@r1", "nope@2026-09-01"])
@pytest.mark.asyncio
async def test_sr20_an_unknown_pin_is_not_found(registry: RegistryService, pin: str) -> None:
    await _seed_two_revisions(registry)

    with pytest.raises(PinNotFound) as info:
        await registry.resolve_pin(pin)

    assert info.value.code == "replay_pin_not_found"


@pytest.mark.asyncio
async def test_sr20_a_malformed_pin_is_invalid(registry: RegistryService) -> None:
    with pytest.raises(InvalidPin):
        await registry.resolve_pin("kevins-best@r0")


@pytest.mark.asyncio
async def test_sr12_lost_race_on_first_submit_resolves_to_winner(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = TortoiseSystemRepository()
    service = RegistryService(repository, FakeFingerprinter())
    await _submit(service, "U_R", "a", ANA)
    real = repository.find_revision_by_fingerprint
    calls: list[str] = []

    async def stale_first_read(fingerprint: str, *, connection: object | None = None):
        calls.append(fingerprint)
        if len(calls) == 1:
            return None  # a stale read: the winner committed after it
        return await real(fingerprint, connection=connection)

    monkeypatch.setattr(repository, "find_revision_by_fingerprint", stale_first_read)

    resolution = await _submit(service, "U_R", "b", BRUNO)

    assert resolution.outcome == "renamed_notice"
    assert resolution.notice == SystemAlreadyNamed("a", ANA)
    # INVARIANT: the savepoint removed the loser's System("b") row with its failed revision.
    assert await _counts() == (1, 1)


class _ScriptedConflicts:
    """Wraps a repository: the first `n` writes raise RegistryWriteConflict."""

    def __init__(self, inner: TortoiseSystemRepository, conflicts: int) -> None:
        self._inner = inner
        self.remaining = conflicts

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def create_system_with_first_revision(self, **kwargs):
        if self.remaining > 0:
            self.remaining -= 1
            raise RegistryWriteConflict("scripted")
        return await self._inner.create_system_with_first_revision(**kwargs)

    async def create_next_revision(self, **kwargs):
        if self.remaining > 0:
            self.remaining -= 1
            raise RegistryWriteConflict("scripted")
        return await self._inner.create_next_revision(**kwargs)


@pytest.mark.asyncio
async def test_a_write_that_loses_a_race_twice_is_a_registry_conflict(tortoise_db: None) -> None:
    repository = _ScriptedConflicts(TortoiseSystemRepository(), conflicts=2)
    service = RegistryService(cast(SystemRepository, repository), FakeFingerprinter())

    with pytest.raises(RegistryConflict) as info:
        await _submit(service, "U_1", "kevins-best", KEVIN)

    assert info.value.code == "registry_conflict"
    assert await _counts() == (0, 0)


@pytest.mark.asyncio
async def test_a_write_that_loses_one_race_is_retried_once_and_succeeds(tortoise_db: None) -> None:
    repository = _ScriptedConflicts(TortoiseSystemRepository(), conflicts=1)
    service = RegistryService(cast(SystemRepository, repository), FakeFingerprinter())

    resolution = await _submit(service, "U_1", "kevins-best", KEVIN)

    assert resolution.outcome == "new"
    assert await _counts() == (1, 1)


@pytest.mark.asyncio
async def test_sr_d3_a_lost_name_race_ends_in_name_taken(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The loser's `find_system_by_name` saw no system (stale); its write then hits UNIQUE(name).
    repository = TortoiseSystemRepository()
    service = RegistryService(repository, FakeFingerprinter())
    await _submit(service, "U_W", "opus-5.5", ANA)
    real = repository.find_system_by_name
    seen = 0

    async def stale_first_name_read(name: str, *, connection: object | None = None):
        nonlocal seen
        seen += 1
        return None if seen == 1 else await real(name, connection=connection)

    monkeypatch.setattr(repository, "find_system_by_name", stale_first_name_read)

    with pytest.raises(SystemNameTaken):
        await _submit(service, "U_L", "opus-5.5", BRUNO)

    assert await _counts() == (1, 1)


@pytest.mark.asyncio
async def test_sr_d4_a_lost_revision_race_takes_the_next_number(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = TortoiseSystemRepository()
    service = RegistryService(repository, FakeFingerprinter())
    await _seed_two_revisions(service)
    real = repository._next_revision_number
    calls = 0

    async def stale_number(connection, system_id: UUID) -> int:
        # A stale max read: as if this task read before a racing writer committed revision 2.
        nonlocal calls
        calls += 1
        number = await real(connection, system_id)
        return number - 1 if calls == 1 else number

    monkeypatch.setattr(repository, "_next_revision_number", stale_number)

    resolution = await _submit(service, "U_3", "x", KEVIN, revision_of="kevins-best")

    assert resolution.revision is not None and resolution.revision.revision == 3
    numbers = sorted(await SystemRevision.all().values_list("revision", flat=True))
    assert numbers == [1, 2, 3]


@pytest.mark.asyncio
async def test_sr8_h3_sdk_recipe_rename_returns_notice(tortoise_db: None) -> None:
    # The REAL adapter, not the fake: a recipe rename must not make a new fingerprint (SR-H3, D3).
    vectors = {vector["id"]: vector for vector in _vectors()["vectors"]}
    service = RegistryService(TortoiseSystemRepository(), Url4Fingerprinter())

    first = await service.resolve_for_submit(
        vectors["c08-b1"]["linked_url4"], "opus-5.5", None, ANA, "public"
    )
    second = await service.resolve_for_submit(
        vectors["c09-b3"]["linked_url4"], "bruno-opus", None, BRUNO, "public"
    )

    assert first.outcome == "new"
    assert second.outcome == "renamed_notice"
    assert second.notice == SystemAlreadyNamed("opus-5.5", ANA)
    assert second.revision is not None and second.revision.revision == 1
    assert await _counts() == (1, 1)


def test_the_app_wires_the_registry_service_with_the_real_adapters(tmp_path: Path) -> None:
    app = create_app(Settings(database_url=f"sqlite://{tmp_path / 's.sqlite3'}", cors_origins=[]))

    registry = app.state.system_registry

    assert isinstance(registry, RegistryService)
    assert isinstance(registry._repository, TortoiseSystemRepository)
    assert isinstance(registry._fingerprinter, Url4Fingerprinter)


@pytest.mark.asyncio
async def test_sr20_a_system_with_no_revision_is_not_found_by_name(tortoise_db: None) -> None:
    # INVARIANT: the registry writes a system and its first revision together, so this row only
    # exists if something else wrote it. Resolving it must be a clean 404, never an IndexError.
    await System.create(name="bare", owner=KEVIN)
    service = RegistryService(TortoiseSystemRepository(), FakeFingerprinter())

    with pytest.raises(PinNotFound):
        await service.resolve_pin("bare")
