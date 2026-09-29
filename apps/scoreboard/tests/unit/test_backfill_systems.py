"""The `python -m scoreboard.backfill_systems` command: BF-1 to BF-7.

FEATURE: OME-1307 (E14), erd.md §6.4 — link legacy public heads to system names, out of band.

INVARIANT under test: the command never changes `spec_id`, `score`, `content_hash` or any ranked
column, never merges two heads, and never reads a private head (I-N4).
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tortoise import Tortoise

import scoreboard.backfill_systems as module
from scoreboard.adapters.url4_fingerprinter import Url4Fingerprinter
from scoreboard.backfill_systems import BackfillRow, backfill_systems, format_report, main
from scoreboard.core.registry import RegistryService, RegistryWriteConflict
from scoreboard.db import close_db, init_db
from scoreboard.scores.models import Benchmark, Score, System, SystemRevision
from scoreboard.scores.store import ScoreStore
from scoreboard.scores.system_registry_store import TortoiseSystemRepository
from tests.unit.registry.conftest import FakeFingerprinter, fingerprint_of

T0 = datetime(2026, 1, 1, tzinfo=UTC)
KEVIN = "kevin@x.org"
ANA = "ana@x.org"


async def _board(board_id: str, visibility: str | None = "public") -> None:
    await Benchmark.create(id=board_id, display_name=board_id, visibility=visibility)


async def _head(
    *,
    board: str = "b1",
    spec_id: str = "kevins-best",
    url4: str = "U_1",
    submitted_by: str | None = KEVIN,
    revision: str | None = "rev-1",
    minute: int = 0,
    score: float = 0.5,
) -> Score:
    row = await Score.create(
        benchmark_id=board,
        spec_id=spec_id,
        url4_expression=url4,
        submitted_by=submitted_by,
        score=score,
        total_questions=10,
        ran_with_providers=["openrouter"],
        benchmark_revision=revision,
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
    )
    # WHY an explicit time: `submitted_at` is auto_now_add, so two heads created back to back tie,
    # and the command's order (submitted_at, then id) would depend on random ids.
    await Score.filter(id=row.id).update(submitted_at=T0 + timedelta(minutes=minute))
    return row


def _service() -> tuple[TortoiseSystemRepository, RegistryService]:
    repository = TortoiseSystemRepository()
    return repository, RegistryService(repository, FakeFingerprinter())


async def _run(*, apply: bool) -> list[BackfillRow]:
    repository, service = _service()
    return await backfill_systems(apply=apply, repository=repository, registry=service)


def _actions(rows: list[BackfillRow]) -> list[str]:
    return [row.action for row in rows]


async def _linked() -> dict[uuid.UUID, uuid.UUID | None]:
    return {row.id: row.system_revision_id for row in await Score.all()}


@pytest.mark.asyncio
async def test_bf1_dry_run_writes_nothing(tortoise_db: None) -> None:
    await _board("b1")
    await _head(url4="U_1", spec_id="one", minute=0)
    await _head(url4="U_2", spec_id="two", minute=1)
    await _head(url4="U_3", spec_id="three", minute=2)

    rows = await _run(apply=False)

    assert Counter(_actions(rows)) == {"claim": 3, "link": 3}
    assert await System.all().count() == 0
    assert await SystemRevision.all().count() == 0
    assert set((await _linked()).values()) == {None}


@pytest.mark.asyncio
async def test_bf1_apply_writes_what_the_dry_run_reported(tortoise_db: None) -> None:
    await _board("b1")
    await _head(url4="U_1", spec_id="one", minute=0)
    await _head(url4="U_2", spec_id="two", minute=1)
    dry = await _run(apply=False)

    applied = await _run(apply=True)

    assert _actions(applied) == _actions(dry)
    assert await System.all().count() == 2
    assert await SystemRevision.all().count() == 2
    assert None not in (await _linked()).values()


@pytest.mark.asyncio
async def test_bf1b_dry_run_links_nothing_for_an_already_registered_fingerprint(
    tortoise_db: None,
) -> None:
    # INVARIANT: "dry run writes nothing" also holds when the head's fingerprint is registered,
    # where the code has a real revision id to write (BF-1 seeds fresh heads only).
    await _board("b1")
    repository, service = _service()
    await service.resolve_for_submit("U_1", "kevins-best", None, KEVIN, "public")
    await _head(url4="U_1", spec_id="kevins-best")

    rows = await backfill_systems(apply=False, repository=repository, registry=service)

    assert _actions(rows) == ["link"]
    assert set((await _linked()).values()) == {None}
    assert await System.all().count() == 1  # only the registration above


@pytest.mark.asyncio
async def test_bf2_earliest_head_claims_its_spec_id(tortoise_db: None) -> None:
    await _board("b1")
    await _board("b2")
    early = await _head(board="b1", spec_id="kevins-best", url4="U_1", submitted_by=KEVIN, minute=0)
    late = await _head(board="b2", spec_id="kevins-best", url4="U_1", submitted_by=ANA, minute=5)

    rows = await _run(apply=True)

    system = await System.get(name="kevins-best")
    assert system.owner == KEVIN  # the earlier head's submitter
    assert await System.all().count() == 1
    revision = await SystemRevision.get(fingerprint=fingerprint_of("U_1"))
    linked = await _linked()
    assert linked[early.id] == revision.id
    assert linked[late.id] == revision.id
    assert _actions(rows) == ["claim", "link", "link"]


@pytest.mark.asyncio
async def test_bf2_a_head_is_ordered_by_submitted_at_not_by_creation(tortoise_db: None) -> None:
    await _board("b1")
    await _board("b2")
    await _head(board="b2", spec_id="kevins-best", url4="U_1", submitted_by=ANA, minute=9)
    await _head(board="b1", spec_id="kevins-best", url4="U_1", submitted_by=KEVIN, minute=1)

    await _run(apply=True)

    assert (await System.get(name="kevins-best")).owner == KEVIN


@pytest.mark.asyncio
async def test_bf3_name_clash_is_reported_not_applied(tortoise_db: None) -> None:
    await _board("b1")
    first = await _head(spec_id="kevins-best", url4="U_1", minute=0)
    second = await _head(spec_id="kevins-best", url4="U_2", minute=1)

    rows = await _run(apply=True)

    assert _actions(rows) == ["claim", "link", "clash"]
    assert await System.all().count() == 1
    linked = await _linked()
    assert linked[first.id] is not None
    assert linked[second.id] is None
    assert rows[-1].score_id == second.id and rows[-1].name == "kevins-best"


@pytest.mark.asyncio
async def test_bf3_a_clash_with_a_registered_system_is_reported(tortoise_db: None) -> None:
    await _board("b1")
    repository, service = _service()
    await service.resolve_for_submit("U_OTHER", "kevins-best", None, ANA, "public")
    await _head(spec_id="kevins-best", url4="U_1")

    rows = await backfill_systems(apply=True, repository=repository, registry=service)

    assert _actions(rows) == ["clash"]
    assert await System.all().count() == 1
    assert await SystemRevision.all().count() == 1


@pytest.mark.asyncio
async def test_bf3b_dry_run_predicts_the_clash_with_a_registered_system(
    tortoise_db: None,
) -> None:
    # INVARIANT: the dry run reports what `--apply` will do, also when the name is taken in the
    # database (not only in this pass's plan).
    await _board("b1")
    repository, service = _service()
    await service.resolve_for_submit("U_OTHER", "kevins-best", None, ANA, "public")
    await _head(spec_id="kevins-best", url4="U_1")

    dry = await backfill_systems(apply=False, repository=repository, registry=service)
    applied = await backfill_systems(apply=True, repository=repository, registry=service)

    assert _actions(dry) == ["clash"]
    assert _actions(applied) == _actions(dry)
    assert await System.all().count() == 1


@pytest.mark.asyncio
async def test_bf3_a_claim_that_loses_a_race_is_reported_as_a_clash(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _board("b1")
    head = await _head(spec_id="kevins-best", url4="U_1")
    repository, service = _service()

    async def lose_the_race(**kwargs: object) -> None:
        raise RegistryWriteConflict("another writer took the name")

    monkeypatch.setattr(repository, "create_system_with_first_revision", lose_the_race)

    rows = await backfill_systems(apply=True, repository=repository, registry=service)

    assert _actions(rows) == ["clash"]
    assert (await Score.get(id=head.id)).system_revision_id is None
    assert await System.all().count() == 0


@pytest.mark.asyncio
async def test_bf4_legacy_heads_are_never_merged(tortoise_db: None) -> None:
    await _board("b1")
    await _head(url4="U_1", spec_id="kevins-best", revision="rev-1", minute=0, score=0.9)
    await _head(url4="U_1", spec_id="kevins-best", revision="rev-1", minute=1, score=0.8)
    before = [entry.model_dump() for entry in await ScoreStore().leaderboard("b1", top_n=None)]

    rows = await _run(apply=True)

    assert Counter(_actions(rows)) == {"claim": 1, "link": 1, "duplicate_head": 1}
    assert await Score.all().count() == 2  # nothing merged
    linked = await _linked()
    assert list(linked.values()).count(None) == 1  # the second head stays unlinked
    after = [entry.model_dump() for entry in await ScoreStore().leaderboard("b1", top_n=None)]
    assert after == before


@pytest.mark.asyncio
async def test_bf4_the_same_fingerprint_on_another_revision_links_both(tortoise_db: None) -> None:
    await _board("b1")
    await _head(url4="U_1", revision="rev-1", minute=0)
    await _head(url4="U_1", revision="rev-2", minute=1)

    rows = await _run(apply=True)

    assert _actions(rows) == ["claim", "link", "link"]
    assert None not in (await _linked()).values()


@pytest.mark.asyncio
async def test_bf4_a_head_already_linked_on_that_board_and_revision_is_a_duplicate(
    tortoise_db: None,
) -> None:
    await _board("b1")
    repository, service = _service()
    resolution = await service.resolve_for_submit("U_1", "kevins-best", None, KEVIN, "public")
    assert resolution.revision is not None
    linked = await _head(url4="U_1", spec_id="kevins-best", revision="rev-1", minute=0)
    await Score.filter(id=linked.id).update(system_revision_id=resolution.revision.id)
    stray = await _head(url4="U_1", spec_id="kevins-best", revision="rev-1", minute=1)

    rows = await backfill_systems(apply=True, repository=repository, registry=service)

    assert _actions(rows) == ["duplicate_head"]
    assert (await Score.get(id=stray.id)).system_revision_id is None


@pytest.mark.asyncio
async def test_bf4_two_heads_with_no_benchmark_revision_are_still_one_key(
    tortoise_db: None,
) -> None:
    await _board("b1")
    await _head(url4="U_1", revision=None, minute=0)
    await _head(url4="U_1", revision=None, minute=1)

    rows = await _run(apply=True)

    assert Counter(_actions(rows)) == {"claim": 1, "link": 1, "duplicate_head": 1}


@pytest.mark.asyncio
async def test_bf_a_fingerprint_registered_under_another_name_is_a_name_mismatch(
    tortoise_db: None,
) -> None:
    await _board("b1")
    repository, service = _service()
    await service.resolve_for_submit("U_1", "official-name", None, ANA, "public")
    head = await _head(url4="U_1", spec_id="my-name")

    rows = await backfill_systems(apply=True, repository=repository, registry=service)

    assert _actions(rows) == ["name_mismatch"]
    assert (await Score.get(id=head.id)).system_revision_id is None


@pytest.mark.asyncio
async def test_bf_a_head_of_a_registered_fingerprint_with_the_same_name_is_linked(
    tortoise_db: None,
) -> None:
    await _board("b1")
    repository, service = _service()
    resolution = await service.resolve_for_submit("U_1", "kevins-best", None, KEVIN, "public")
    head = await _head(url4="U_1", spec_id="Kevins-Best")

    rows = await backfill_systems(apply=True, repository=repository, registry=service)

    assert _actions(rows) == ["link"]
    assert resolution.revision is not None
    assert (await Score.get(id=head.id)).system_revision_id == resolution.revision.id


@pytest.mark.asyncio
async def test_bf5_private_heads_are_skipped(tortoise_db: None) -> None:
    await _board("pub")
    await _board("priv", visibility="private")
    await _board("legacy-null", visibility=None)
    private = await _head(board="priv", spec_id="secret", url4="U_P")
    await _head(board="legacy-null", spec_id="null-vis", url4="U_N", minute=1)

    rows = await _run(apply=True)

    assert {row.benchmark_id for row in rows} == {"legacy-null"}  # NULL visibility reads public
    assert await System.filter(name="secret").count() == 0
    assert (await Score.get(id=private.id)).system_revision_id is None


@pytest.mark.asyncio
async def test_bf6_rerun_is_idempotent(tortoise_db: None) -> None:
    await _board("b1")
    await _head(url4="U_1", spec_id="one", minute=0)
    await _head(url4="U_2", spec_id="two", minute=1)
    await _head(url4="U_3", spec_id="one", minute=2)  # a clash: stays unlinked
    await _run(apply=True)
    counts = (await System.all().count(), await SystemRevision.all().count())
    linked = await _linked()

    rows = await _run(apply=True)

    assert "claim" not in _actions(rows)
    assert (await System.all().count(), await SystemRevision.all().count()) == counts
    assert await _linked() == linked


@pytest.mark.asyncio
async def test_bf7_bad_heads_are_reported(tortoise_db: None) -> None:
    await _board("b1")
    bad_name = await _head(spec_id="a/b", url4="U_1", minute=0)
    bad_url4 = await _head(spec_id="fine", url4="invalid!", minute=1)
    no_owner = await _head(spec_id="orphan", url4="U_3", submitted_by=None, minute=2)

    rows = await _run(apply=True)

    by_score = {row.score_id: row for row in rows}
    assert by_score[bad_name.id].action == "invalid_name"
    assert by_score[bad_url4.id].action == "invalid_url4"
    assert by_score[no_owner.id].action == "no_owner"
    assert len(rows) == 3
    assert set((await _linked()).values()) == {None}
    assert await System.all().count() == 0


@pytest.mark.asyncio
async def test_bf7_an_oversize_url4_is_reported_as_invalid_url4(tortoise_db: None) -> None:
    await _board("b1")
    head = await _head(url4="a" * 32_001)

    rows = await _run(apply=True)

    assert [(row.action, row.score_id) for row in rows] == [("invalid_url4", head.id)]


@pytest.mark.asyncio
async def test_bf7_a_deeply_nested_head_is_reported_and_the_run_goes_on(
    tortoise_db: None,
) -> None:
    # WHY the real adapter: the failure is url4 recursing, which the fake never does. One such
    # legacy head must not abort the whole run with a traceback.
    await _board("b1")
    nested = "/openrouter/model($input)"
    for _ in range(200):
        nested = f"(m:0.0:{nested})!'x'"
    deep = await _head(spec_id="deep", url4=nested, minute=0)
    fine = await _head(spec_id="fine", url4="(a:/m()!'x')!'$a'", minute=1)
    repository = TortoiseSystemRepository()
    service = RegistryService(repository, Url4Fingerprinter())

    rows = await backfill_systems(apply=True, repository=repository, registry=service)

    assert _actions(rows) == ["invalid_url4", "claim", "link"]
    assert rows[0].score_id == deep.id
    linked = await _linked()
    assert linked[deep.id] is None
    assert linked[fine.id] is not None


@pytest.mark.asyncio
async def test_the_command_changes_no_ranked_column(tortoise_db: None) -> None:
    await _board("b1")
    head = await _head(url4="U_1", spec_id="kevins-best", score=0.7)
    before = await Score.get(id=head.id)

    await _run(apply=True)

    after = await Score.get(id=head.id)
    for column in ("spec_id", "score", "content_hash", "benchmark_id", "benchmark_revision"):
        assert getattr(after, column) == getattr(before, column)
    assert after.system_revision_id is not None


def test_the_report_names_the_mode_and_counts_each_action() -> None:
    score_id = uuid.uuid4()
    rows = [
        BackfillRow("claim", score_id, "b1", "kevins-best", "new system"),
        BackfillRow("link", score_id, "b1", "kevins-best", "linked"),
        BackfillRow("invalid_name", score_id, "b1", None, "bad name"),
    ]

    dry = format_report(rows, applied=False).splitlines()
    applied = format_report(rows, applied=True).splitlines()

    assert dry[0] == "DRY RUN — nothing written"
    assert applied[0] == "APPLIED"
    assert dry[1].split("\t") == ["claim", str(score_id), "b1", "kevins-best", "new system"]
    assert dry[3].split("\t")[3] == ""  # a missing name is an empty field
    assert {"claim: 1", "link: 1", "invalid_name: 1"} <= set(dry[4:])


@pytest.fixture
def legacy_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    url = f"sqlite://{tmp_path / 'scoreboard.sqlite3'}"
    monkeypatch.setenv("SCOREBOARD_DATABASE_URL", url)

    async def _seed() -> None:
        await init_db(url)
        await Tortoise.generate_schemas(safe=True)
        await _board("b1")
        await _head(spec_id="kevins-best", url4="(a:/m()!'x')!'$a'")
        await close_db()

    asyncio.run(_seed())
    yield url


def _read(url: str) -> tuple[int, int]:
    async def _go() -> tuple[int, int]:
        await init_db(url)
        try:
            return await System.all().count(), await Score.filter(
                system_revision_id__isnull=False
            ).count()
        finally:
            await close_db()

    return asyncio.run(_go())


def test_bf7_the_dry_run_command_prints_the_banner_and_writes_nothing(
    legacy_database: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real_init, real_close = module.init_db, module.close_db

    async def spy_init(url: str) -> None:
        calls.append("init")
        await real_init(url)

    async def spy_close() -> None:
        calls.append("close")
        await real_close()

    monkeypatch.setattr(module, "init_db", spy_init)
    monkeypatch.setattr(module, "close_db", spy_close)

    main(["--dry-run"])

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "DRY RUN — nothing written"
    assert calls == ["init", "close"]
    assert _read(legacy_database) == (0, 0)


def test_the_apply_command_writes_and_prints_applied(
    legacy_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--apply"])

    assert capsys.readouterr().out.splitlines()[0] == "APPLIED"
    assert _read(legacy_database) == (1, 1)


def test_bf7_the_command_requires_exactly_one_mode(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as none_given:
        main([])
    with pytest.raises(SystemExit) as both_given:
        main(["--dry-run", "--apply"])

    assert none_given.value.code == 2
    assert both_given.value.code == 2
