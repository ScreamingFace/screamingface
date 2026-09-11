"""Accepting and storing declared model routes (OME-1181, spec §2.1-§2.2).

The Client truncates every route to its provider prefix before submission, so the board stores
`["openrouter"]` for a fusion of deepseek, kimi and qwen. This field is how the identities
survive the wire. `OME-1180` makes the Client send them; this is the half that accepts them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore, _content_hash

ROUTES = [
    "openrouter/deepseek/deepseek-v4-pro",
    "openrouter/moonshotai/kimi-k2.6",
    "openrouter/qwen/qwen3.6-plus",
]


def _submission(
    *,
    models: list[str] | None = None,
    ran_with_providers: list[str] | None = None,
) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id="spec-1",
        url4_expression="url4://benchmark/hle/spec-1",
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
