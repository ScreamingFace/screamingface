from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from scoreboard.export_private_submissions import format_jsonl
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore, _content_hash

ALICE = "alice@example.test"
BOB = "bob@example.test"


def _submission(
    *,
    submitted_by: str = ALICE,
    authors: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id="spec-1",
        url4_expression="url4://benchmark/hle/spec-1",
        submitted_by=submitted_by,
        authors=authors,
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openai"],
        run_cost_usd=Decimal("1.000000"),
        metadata=metadata,
    )


def test_submission_accepts_one_to_ten_email_authors_in_order() -> None:
    authors = [f"author-{index}@example.test" for index in range(10)]

    submission = _submission(authors=authors)

    assert submission.authors == authors


@pytest.mark.parametrize(
    "authors",
    [
        [],
        [f"author-{index}@example.test" for index in range(11)],
        ["not-an-email"],
        ["alice@example"],
        ["alice@@example.test"],
        ["alice @example.test"],
        ["@example.test"],
        ["alice@example..test"],
        [f"{'a' * 244}@example.test"],
    ],
)
def test_submission_rejects_unbounded_or_malformed_authors(authors: list[str]) -> None:
    with pytest.raises(ValidationError):
        _submission(authors=authors)


def test_authors_do_not_change_recipe_identity() -> None:
    original = _submission(authors=[ALICE])
    corrected = _submission(authors=[ALICE, BOB])

    assert _content_hash(original) == _content_hash(corrected)


def test_score_model_has_nullable_json_author_storage() -> None:
    field = Score._meta.fields_map["authors"]

    assert field.null is True
    assert field.__class__.__name__ == "JSONField"


@pytest.mark.asyncio
async def test_legacy_submission_reads_submitter_as_sole_author(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    score, created = await store.submit(_submission())
    stored = await Score.get(id=score.id)

    assert created is True
    assert stored.authors is None
    assert score.authors == [ALICE]


@pytest.mark.asyncio
async def test_authors_are_redacted_in_json_but_full_in_staff_data(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    score, _ = await store.submit(_submission(authors=[ALICE, BOB]))

    public = json.loads(score.model_dump_json())
    staff = json.loads(format_jsonl([score]))

    assert public["authors"] == ["alice", "bob"]
    assert staff["authors"] == [ALICE, BOB]


@pytest.mark.asyncio
async def test_leaderboard_and_history_include_explicit_authors(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    await store.submit(_submission(authors=[ALICE, BOB]))

    leaderboard = await store.leaderboard("hle")
    history = await store.list_for_spec("hle", "spec-1")

    assert leaderboard[0].authors == [ALICE, BOB]
    assert history[0].authors == [ALICE, BOB]
    assert json.loads(leaderboard[0].model_dump_json())["authors"] == ["alice", "bob"]


@pytest.mark.asyncio
async def test_author_credit_never_grants_private_board_ownership(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    await store.submit(
        _submission(authors=[ALICE, BOB]),
        identity_verified=True,
    )

    assert len(await store.list_owned_entries("hle", owner=ALICE)) == 1
    assert await store.list_owned_entries("hle", owner=BOB) == []


@pytest.mark.asyncio
async def test_same_submitter_can_correct_authors_and_metadata_on_dedup(
    tortoise_db: None,
) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    first, first_created = await store.submit(
        _submission(authors=[ALICE], metadata={"note": "old"})
    )

    replay, replay_created = await store.submit(
        _submission(authors=[ALICE, BOB], metadata={"note": "corrected"})
    )
    stored = await Score.get(id=first.id)

    assert first_created is True
    assert replay_created is False
    assert replay.id == first.id
    assert replay.authors == [ALICE, BOB]
    assert replay.metadata == {"note": "corrected"}
    assert stored.authors == [ALICE, BOB]
    assert stored.metadata == {"note": "corrected"}
    assert await Score.all().count() == 1


@pytest.mark.asyncio
async def test_omitted_replay_metadata_does_not_erase_explicit_values(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    first, _ = await store.submit(_submission(authors=[ALICE, BOB], metadata={"note": "keep"}))

    replay, created = await store.submit(_submission())

    assert created is False
    assert replay.id == first.id
    assert replay.authors == [ALICE, BOB]
    assert replay.metadata == {"note": "keep"}


@pytest.mark.asyncio
async def test_another_submitter_cannot_rewrite_public_author_credit(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    original, _ = await store.submit(_submission(authors=[ALICE], metadata={"owner": "alice"}))

    replay, created = await store.submit(
        _submission(
            submitted_by=BOB,
            authors=["attacker@example.test"],
            metadata={"owner": "bob"},
        )
    )
    stored = await Score.get(id=original.id)

    assert created is False
    assert replay.id == original.id
    assert replay.authors == [ALICE]
    assert replay.metadata == {"owner": "alice"}
    assert stored.authors == [ALICE]
    assert stored.metadata == {"owner": "alice"}


def test_portal_renders_author_lists_in_leaderboard_and_history() -> None:
    portal = Path(__file__).resolve().parents[2] / "portal"

    assert 'key: "submitted_by", label: "Submitter"' in (portal / "benchmark.js").read_text()
    assert "P.formatSubmitter(entry.submitted_by)" in (portal / "benchmark.js").read_text()
    assert "P.formatAuthors(entry.authors)" in (portal / "benchmark.js").read_text()
    assert "P.formatSubmitter(s.submitted_by)" in (portal / "spec.js").read_text()
    assert "P.formatAuthors(s.authors)" in (portal / "spec.js").read_text()
    assert "<th>Submitter</th>" in (portal / "spec.html").read_text()
    assert "<th>Authors</th>" in (portal / "spec.html").read_text()


@pytest.mark.asyncio
async def test_owned_entries_carry_every_field_with_a_non_default_value(
    tortoise_db: None,
) -> None:
    """`list_owned_entries` hand-builds the DTO, so every declared field must be copied.

    WHY this exists next to `test_owned_entries_project_every_declared_field_from_the_row`
    rather than instead of it: that guard compares each field to the row, but its fixture leaves
    the NULLABLE ones unset, so `None == None` passed for `authors` while the projection never
    copied it. The bug shipped past a guard written to catch exactly it.

    A guard of this shape is only as strong as its fixture. Every nullable field here therefore
    carries a value that differs from the DTO default, so a field added to `LeaderboardEntry` and
    forgotten in the projection fails here whatever its type.

    INVARIANT: a private board is the ONLY surface where a participant sees their own credit line
    (OME-894 D2 scopes reads to the submitter, and `entries` is empty for everyone), so this
    projection is where an omission does the most damage and shows the least.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    submission = _submission(authors=[ALICE, BOB], metadata={"benchmark_revision": "rev-9"})
    await store.submit(submission, identity_verified=True)
    row = await Score.get(spec_id="spec-1")

    entries = await store.list_owned_entries("hle", owner=ALICE)

    assert len(entries) == 1
    defaults = {
        name: field.default
        for name, field in type(entries[0]).model_fields.items()
        if not field.is_required()
    }
    for name in type(entries[0]).model_fields:
        actual = getattr(entries[0], name)
        assert actual == getattr(row, name), (
            f"{name!r} is declared on LeaderboardEntry but list_owned_entries does not carry it "
            "from the Score row"
        )
        if name in defaults:
            assert actual != defaults[name], (
                f"{name!r} is nullable and this fixture left it at its DTO default, so the "
                "comparison above cannot tell a copied field from an omitted one. Give it a "
                "distinctive value."
            )
