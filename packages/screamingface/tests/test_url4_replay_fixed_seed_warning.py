"""A raw url4 replay with a run seed warns about own-seed calls too (OME-1289, U1 follow-through).

WHY: the Engine lets a call that sets its own ``seed`` keep it, so such calls send the same request
in every sitting. The Recipe path already warns (``test_fixed_seed_sitting_warning.py``); a replayed
url4 is how a researcher reproduces a sitting, so it must warn too, with the same text.
"""

from __future__ import annotations

import warnings

import httpx
import pytest
from _nodes import fusion_node
from _reducer_fixtures import FixtureVote, fixture_operators, operators_response
from test_client_run import _AsyncReplayTransport, _ReplayTransport
from test_fixed_seed_sitting_warning import _run_sync as _run_recipe_sync
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_BASE = "https://engine.example"
_MODEL = "provider/opus"


def _samples_fusion() -> sf.Recipe:
    return fusion_node(sf.samples(_MODEL, 3), FixtureVote())


def _replay(recipe: sf.Recipe) -> str:
    candidate = compile_candidate(recipe, operators=fixture_operators()).url4
    assert candidate is not None
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("fixture", name="result", weight=0.0),
            intent=text("$result"),
        )
    )


def _engine(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/operators":
        return operators_response()
    return httpx.Response(404)


def _fixed(recorded: list[warnings.WarningMessage]) -> list[warnings.WarningMessage]:
    return [w for w in recorded if issubclass(w.category, sf.FixedSeedSittingWarning)]


def _sync_replay(
    recipe: sf.Recipe, answer_seed: int | None
) -> tuple[list[warnings.WarningMessage], _ReplayTransport]:
    transport = _ReplayTransport()
    replay = _replay(recipe)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        with sf.Client(
            engine_url=_BASE, http_transport=httpx.MockTransport(_engine), run_transport=transport
        ) as client:
            client.evaluate(replay, progress=False, answer_seed=answer_seed)
    return _fixed(recorded), transport


def test_a_replayed_samples_fusion_with_a_run_seed_warns_once_and_still_runs() -> None:
    fixed, transport = _sync_replay(_samples_fusion(), answer_seed=3)

    assert len(fixed) == 1
    message = str(fixed[0].message)
    assert "a run seed is set, but 3 calls set their own seed: op_model_1 (" in message
    assert "op_model_3 (" in message
    assert isinstance(fixed[0].message, sf.EvaluationWarning)
    assert fixed[0].filename == __file__
    # WHY: a warning, not a refusal; the replay reached the run transport.
    assert transport.candidate is not None


def test_the_replay_text_is_the_recipe_text() -> None:
    from_recipe, _ = _run_recipe_sync(_samples_fusion(), answer_seed=3)
    from_replay, _ = _sync_replay(_samples_fusion(), answer_seed=3)

    assert len(from_recipe) == len(from_replay) == 1
    assert str(from_replay[0].message) == str(from_recipe[0].message)


def test_no_warning_without_a_run_seed() -> None:
    fixed, transport = _sync_replay(_samples_fusion(), answer_seed=None)

    assert fixed == []
    assert transport.candidate is not None


def test_no_warning_when_no_call_sets_a_seed() -> None:
    recipe = fusion_node(
        [sf.Model(_MODEL, params={"temperature": 0.2}), sf.Model(_MODEL)],
        FixtureVote(),
    )

    fixed, transport = _sync_replay(recipe, answer_seed=3)

    assert fixed == []
    assert transport.candidate is not None


@pytest.mark.asyncio
async def test_async_replayed_samples_fusion_with_a_run_seed_warns_once_and_still_runs() -> None:
    transport = _AsyncReplayTransport()
    replay = _replay(_samples_fusion())

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        async with sf.AsyncClient(
            engine_url=_BASE, http_transport=httpx.MockTransport(_engine), run_transport=transport
        ) as client:
            await client.evaluate(replay, progress=False, answer_seed=3)

    fixed = _fixed(recorded)
    assert len(fixed) == 1
    assert "3 calls set their own seed: op_model_1 (" in str(fixed[0].message)
    assert fixed[0].filename == __file__
    assert transport.candidate is not None
