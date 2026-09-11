"""Accepting and storing declared model routes (OME-1181, spec §2.1-§2.2).

The Client truncates every route to its provider prefix before submission, so the board stores
`["openrouter"]` for a fusion of deepseek, kimi and qwen. This field is how the identities
survive the wire. `OME-1180` makes the Client send them; this is the half that accepts them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tortoise.queryset import QuerySet

from scoreboard.export_private_submissions import format_jsonl_bytes
from scoreboard.scores import store as store_module
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSchema, ScoreSubmission
from scoreboard.scores.store import ScoreStore, _content_hash

ROUTES = [
    "openrouter/deepseek/deepseek-v4-pro",
    "openrouter/moonshotai/kimi-k2.6",
    "openrouter/qwen/qwen3.6-plus",
]


def _schema_row(*, models: list[str] | None) -> ScoreSchema:
    """A stored row as the export and the public GET see it."""
    return ScoreSchema(
        id=uuid4(),
        version=1,
        benchmark_id="hle",
        benchmark_revision="rev-1",
        spec_id="spec-1",
        url4_expression="url4://benchmark/hle/spec-1",
        submitted_by="alice@example.test",
        models=models,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openrouter"],
        ran_at_local=None,
        client_name=None,
        client_version=None,
        client_platform=None,
        verified_by_screamingface=True,
        metadata=None,
        openness_override=None,
        run_cost_usd=None,
    )


def _submission(
    *,
    models: list[str] | None = None,
    ran_with_providers: list[str] | None = None,
    spec_id: str = "spec-1",
    url4: str = "url4://benchmark/hle/spec-1",
) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id=spec_id,
        url4_expression=url4,
        submitted_by="alice@example.test",
        models=models,
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=ran_with_providers or ["openrouter"],
    )


def test_declared_routes_are_accepted_verbatim() -> None:
    submission = _submission(models=ROUTES)

    assert submission.models == ROUTES


def test_models_is_optional_so_older_clients_keep_working() -> None:
    """INVARIANT: this unit DEPLOYS before the Client that populates it (OME-1179 constraint 1).

    `ScoreSubmission` is `extra="forbid"`, so the rollout is one-directional: a Client sending
    an unknown field to an older board gets a 422. The field must therefore be optional here,
    or the deploy order reverses and every in-field submission breaks.
    """
    assert _submission().models is None


def test_an_empty_model_list_is_rejected() -> None:
    """None means "the client did not send them". `[]` would mean "this ran on no models",
    which is not a state any real submission can be in — `CandidateResult.models` is required
    and non-empty at the Client. Silently accepting it would store an unclassifiable row that
    looks populated.
    """
    with pytest.raises(ValidationError):
        _submission(models=[])


@pytest.mark.parametrize(
    "route",
    [
        "has spaces/in-it",
        "trailing/",
        "/leading",
        "double//segment",
        "a" * 256,
    ],
)
def test_malformed_routes_are_rejected(route: str) -> None:
    with pytest.raises(ValidationError):
        _submission(models=[route])


def test_too_many_routes_are_rejected_at_the_boundary() -> None:
    at_cap = [f"provider/model-{index}" for index in range(32)]
    over_cap = [*at_cap, "provider/model-32"]

    assert _submission(models=at_cap).models == at_cap
    with pytest.raises(ValidationError, match="at most 32"):
        _submission(models=over_cap)


def test_an_oversized_model_payload_is_rejected() -> None:
    """WHY a byte cap on top of the route count: 32 routes of 255 characters is still 8 KiB of
    client-controlled text on a public write path. The same reasoning and the same 4096-byte
    limit as `authors` (OME-1109) and `metadata`.
    """
    fat = [f"provider/{'m' * 240}-{index}" for index in range(20)]

    with pytest.raises(ValidationError, match="serialize to at most"):
        _submission(models=fat)


@pytest.mark.asyncio
async def test_declared_routes_survive_storage(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    score, created = await store.submit(_submission(models=ROUTES))
    stored = await Score.get(id=score.id)

    assert created is True
    assert stored.models == ROUTES
    assert score.models == ROUTES


@pytest.mark.asyncio
async def test_a_submission_without_routes_still_succeeds(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    score, created = await store.submit(_submission())
    stored = await Score.get(id=score.id)

    assert created is True
    assert stored.models is None
    assert score.models is None


@pytest.mark.asyncio
async def test_providers_are_derived_from_the_routes_when_they_are_present(
    tortoise_db: None,
) -> None:
    """The two fields describe the same thing, so only one of them should be authoritative.

    The Client already derives `ran_with_providers` from these routes; recomputing it here
    means a submission cannot assert a provider its own routes contradict.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    score, _ = await store.submit(
        _submission(
            models=["anthropic/claude-opus-4.8", "openrouter/qwen/qwen3.6-plus"],
            ran_with_providers=["openrouter"],
        )
    )
    stored = await Score.get(id=score.id)

    assert stored.ran_with_providers == ["anthropic", "openrouter"]


@pytest.mark.asyncio
async def test_the_clients_providers_are_kept_when_no_routes_are_declared(
    tortoise_db: None,
) -> None:
    """INVARIANT: no routes means nothing to derive from. The truncation is lossy, so there is
    no way back from ["openrouter"] to the models — the client's value is all there is.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    score, _ = await store.submit(_submission(ran_with_providers=["huggingface", "ollama"]))
    stored = await Score.get(id=score.id)

    assert stored.ran_with_providers == ["huggingface", "ollama"]


@pytest.mark.asyncio
async def test_derived_providers_preserve_order_and_collapse_repeats(
    tortoise_db: None,
) -> None:
    """Order is part of what happened, not incidental serialization — `_content_hash` hashes
    `ran_with_providers` as sent, unsorted, for exactly that reason (OME-391).
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    score, _ = await store.submit(
        _submission(
            models=[
                "openrouter/qwen/qwen3.6-plus",
                "anthropic/claude-opus-4.8",
                "openrouter/deepseek/deepseek-v4-pro",
            ]
        )
    )
    stored = await Score.get(id=score.id)

    assert stored.ran_with_providers == ["openrouter", "anthropic"]


def test_deriving_providers_does_not_change_recipe_identity() -> None:
    """INVARIANT: `_content_hash` reads the WIRE `ran_with_providers`, never the derived value.

    Hashing the derived value would recompute identity for every recipe whose client-sent
    providers differ from its routes — and, once OME-1180 ships, for every row submitted before
    it. Each of those would stop deduplicating to its stored twin and create a second row
    instead. Storage may be corrected; identity may not be rewritten underneath it.
    """
    honest = _submission(models=["anthropic/claude-opus-4.8"], ran_with_providers=["anthropic"])
    contradictory = _submission(
        models=["anthropic/claude-opus-4.8"], ran_with_providers=["openrouter"]
    )

    assert _content_hash(honest) != _content_hash(contradictory)


@pytest.mark.asyncio
async def test_a_replay_by_the_same_submitter_fills_in_missing_routes(
    tortoise_db: None,
) -> None:
    """FEATURE: OME-1179 Q3 — the whole reason rows can ever become classifiable.

    Every row predates the Client that sends routes. Without this, a submitter who re-runs
    after OME-1180 ships gets deduplicated to their old row and the routes are silently
    discarded, so the board keeps a permanent population it cannot classify.

    `models` is deterministic for a given `content_hash`: the hash covers `url4_expression`,
    and the routes are a projection of that same recipe. So a replay carrying different routes
    for the same hash means an inconsistent client, not a legitimate correction.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    first, first_created = await store.submit(_submission())

    replay, replay_created = await store.submit(_submission(models=ROUTES))
    stored = await Score.get(id=first.id)

    assert first_created is True
    assert replay_created is False
    assert replay.id == first.id
    assert stored.models == ROUTES
    assert await Score.all().count() == 1


@pytest.mark.asyncio
async def test_another_submitter_cannot_write_routes_onto_someone_elses_row(
    tortoise_db: None,
) -> None:
    """INVARIANT: the anti-hijack guard covers this field too, for free.

    A public content hash is global across submitters, so without the same-owner requirement
    anyone who copied a team's candidate could rewrite what that team's entry is made of — and
    under OME-1179 D1 a single fabricated closed route flips the entry's published verdict.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    original, _ = await store.submit(_submission(models=ROUTES))

    attacker = _submission(models=["anthropic/claude-opus-4.8"])
    attacker = attacker.model_copy(update={"submitted_by": "mallory@example.test"})
    replay, created = await store.submit(attacker)
    stored = await Score.get(id=original.id)

    assert created is False
    assert replay.id == original.id
    assert stored.models == ROUTES


@pytest.mark.asyncio
async def test_a_replay_without_routes_does_not_erase_stored_ones(tortoise_db: None) -> None:
    """None means "not specified", so an older Client replaying cannot wipe newer provenance —
    the same rule `authors` and `metadata` already follow.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    first, _ = await store.submit(_submission(models=ROUTES))

    replay, created = await store.submit(_submission())
    stored = await Score.get(id=first.id)

    assert created is False
    assert stored.models == ROUTES
    assert replay.models == ROUTES


@pytest.mark.asyncio
async def test_routes_are_read_back_for_a_set_of_score_ids(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    with_routes, _ = await store.submit(_submission(models=ROUTES))
    without, _ = await store.submit(
        _submission(spec_id="spec-2", models=None, url4="url4://benchmark/hle/spec-2")
    )

    found = await store.models_for_score_ids([str(with_routes.id), str(without.id)])

    assert found == {str(with_routes.id): ROUTES, str(without.id): None}


@pytest.mark.asyncio
async def test_an_unknown_id_is_simply_absent(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    assert await store.models_for_score_ids([]) == {}
    assert await store.models_for_score_ids([str(uuid4())]) == {}


@pytest.mark.asyncio
async def test_the_read_is_chunked_and_loses_nothing_across_the_boundary(
    tortoise_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: the frontier is neither small nor bounded.

    Every best-per-spec point can be non-dominated, and spec ids are client-controlled, so the
    id set handed to this read is as large as the board. A single `WHERE id IN (...)` can
    exceed the database's bind-parameter limit — SQLite's default is 999 — which fails at a
    board size nobody will reproduce in a test. Chunking is therefore exercised by shrinking
    the chunk rather than by growing the board.
    """
    monkeypatch.setattr(store_module, "_MODELS_READ_CHUNK", 2)
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    expected: dict[str, list[str]] = {}
    for index in range(5):
        routes = [f"openrouter/vendor-{index}/model-{index}"]
        score, _ = await store.submit(
            _submission(
                spec_id=f"spec-{index}",
                models=routes,
                url4=f"url4://benchmark/hle/spec-{index}",
            )
        )
        expected[str(score.id)] = routes

    found = await store.models_for_score_ids(list(expected))

    assert found == expected


@pytest.mark.asyncio
async def test_the_read_projects_only_the_two_columns_it_needs(tortoise_db: None) -> None:
    """GUARD: `leaderboard.py:270-275` records why the whole-board read stays minimal —
    client-controlled recipes and display metadata must never be materialised en masse. This
    read is scoped to the frontier rather than the board, but it is still unbounded, so the
    same rule applies. A widened projection fails here.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    score, _ = await store.submit(_submission(models=ROUTES))

    captured: list[tuple[str, ...]] = []
    original = QuerySet.values

    def _spy(self: QuerySet[Any], *fields: str, **kwargs: Any) -> Any:
        captured.append(fields)
        return original(self, *fields, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(QuerySet, "values", _spy)
    try:
        await store.models_for_score_ids([str(score.id)])
    finally:
        monkeypatch.undo()

    assert captured == [("id", "models")]


def test_a_legacy_row_serializes_byte_identically_to_before_this_field() -> None:
    """INVARIANT: adding a field must not change what an EXISTING row exports.

    `ScoreSchema` feeds the private JSONL export, and `purge_private_benchmark.export_sha256`
    hashes those exact bytes to authorize a destructive purge against an operator-supplied
    digest. A `"models": null` on every line silently invalidates every export saved before this
    change, so a previously-certified export can no longer authorize its own purge — with no
    underlying row having changed at all.

    `ranking_notice` carries `exclude_if` for precisely this reason (schemas.py:567-573). Found
    in review of PR #922.
    """
    row = _schema_row(models=None)

    exported = format_jsonl_bytes([row])

    assert b'"models"' not in exported
    assert "models" not in json.loads(exported.decode().strip())


def test_a_row_that_declares_routes_does_export_them() -> None:
    """The exclusion is for ABSENCE, not for the field. A row whose routes are known has
    genuinely changed, and staff reading an export must see what it was made of.
    """
    exported = format_jsonl_bytes([_schema_row(models=ROUTES)])

    assert json.loads(exported.decode().strip())["models"] == ROUTES


def test_the_public_score_response_omits_an_absent_models_field() -> None:
    """`ScoreSchema` is the response model for POST /scores and GET /scores/{id}, so this is a
    public payload, not an internal DTO — the Q2 decision recorded it as internal, which was
    wrong. Absent stays absent on the wire rather than becoming an explicit null.
    """
    assert "models" not in json.loads(_schema_row(models=None).model_dump_json())
    assert json.loads(_schema_row(models=ROUTES).model_dump_json())["models"] == ROUTES


@pytest.mark.asyncio
async def test_a_replay_cannot_replace_routes_that_are_already_declared(
    tortoise_db: None,
) -> None:
    """INVARIANT: enrichment FILLS a missing value; it never replaces a present one.

    `_content_hash` excludes `models`, so two submissions differing only in their routes share
    an identity — verified in `test_models_do_not_change_recipe_identity`. Without this rule a
    replay could therefore swap what an entry is made of, and so flip its published openness,
    without changing its identity or its url4 expression. The Q3 decision was to enrich a
    missing value, not to accept a conflicting one. Found in review of PR #922.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    first, _ = await store.submit(_submission(models=ROUTES))

    replay, created = await store.submit(
        _submission(models=["openrouter/anthropic/claude-opus-4.8"])
    )
    stored = await Score.get(id=first.id)

    assert created is False
    assert stored.models == ROUTES
    assert stored.ran_with_providers == ["openrouter"]


def test_models_do_not_change_recipe_identity() -> None:
    """INVARIANT: `models` must NOT enter `_content_hash` (OME-1179 Q3).

    The routes are a richer projection of data already inside `url4_expression`, which IS
    hashed. Adding them would give one recipe two identities purely because a newer Client sent
    more detail about the same run, so the first resubmission after `OME-1180` ships would
    duplicate every row on the board instead of deduplicating to it.
    """
    without = _submission()
    with_routes = _submission(models=ROUTES)

    assert _content_hash(without) == _content_hash(with_routes)
