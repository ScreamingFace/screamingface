"""What the Client sends with a Run so its Report can be rebuilt anywhere (E5 P2 spec D9b; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher who reattaches from another machine,
the Report I get is the one the machine that started the Run would have built.

INVARIANT (D9b): the context holds the benchmark, the selection and each compiled Candidate
without its url4 and seed, which the start holds; the two together give back the same
evaluation and the same Candidates.
"""

from __future__ import annotations

import json

import pytest
from test_transport_artifact_fetch import _candidate

from screamingface._engine.run_request import run_request, start_request
from screamingface._engine.runs import StartRequest
from screamingface._evaluation.model import (
    _compiled_evaluation,
    _with_answer_seed,
    _with_capture,
    _with_replay_frozen_copy,
    _without_cache,
)
from screamingface._results.run_context import evaluation_from_context, run_context
from screamingface.discovery import BenchmarkInfo
from screamingface.errors import ExecutionError

FROZEN_COPY = "fc_" + "a" * 32


def _evaluation(*candidates, selected_cases=(2, 5)):
    return _compiled_evaluation(
        benchmark=BenchmarkInfo("gsm8k", "rev-1", 10, inverted_grade=True),
        limit=None,
        case_count=len(selected_cases),
        candidates=candidates,
        required_models=candidates[0].models,
        selected_cases=selected_cases,
    )


def test_the_context_and_the_starts_give_back_the_same_evaluation() -> None:
    seeded = _with_capture(_with_answer_seed(_candidate(), 7))
    evaluation = _evaluation(seeded)

    context = run_context(evaluation, (seeded,))
    rebuilt, candidates = evaluation_from_context(context, (start_request(seeded),))

    assert candidates == (seeded,)
    assert (rebuilt.benchmark, rebuilt.case_count, rebuilt.selected_cases) == (
        evaluation.benchmark,
        evaluation.case_count,
        evaluation.selected_cases,
    )
    assert rebuilt.required_models == evaluation.required_models


def test_the_context_holds_no_url4_and_no_seed() -> None:
    """The start holds both; the context is kept unread by the Engine (D9b)."""
    seeded = _with_answer_seed(_candidate(), 7)

    candidate = json.loads(run_context(_evaluation(seeded), (seeded,)))["candidates"][0]

    assert "url4" not in candidate and "answer_seed" not in candidate


@pytest.mark.parametrize(
    "stamp",
    [
        lambda c: _without_cache(c),
        lambda c: _with_replay_frozen_copy(c, FROZEN_COPY),
        lambda c: _with_capture(c),
    ],
    ids=["no-cache", "replay", "capture"],
)
def test_each_start_flag_comes_back_on_its_candidate(stamp) -> None:
    candidate = stamp(_candidate())

    _, (rebuilt,) = evaluation_from_context(
        run_context(_evaluation(candidate), (candidate,)), (start_request(candidate),)
    )

    assert rebuilt == candidate


def test_a_start_carries_the_candidates_url4_and_flags() -> None:
    candidate = _without_cache(_with_answer_seed(_candidate(), 3))

    assert start_request(candidate) == StartRequest(
        name="opus", url4=candidate.url4, answer_seed=3, capture=False, use_cache=False
    )


def test_the_request_names_every_candidate_with_its_start_and_the_context() -> None:
    candidate = _candidate()
    evaluation = _evaluation(candidate)

    request = run_request(evaluation, (candidate,), detach=True, deadline_s=60)

    assert request.candidates == (start_request(candidate),)
    assert (request.benchmark, request.case_count) == ("gsm8k", 2)
    assert (request.detach, request.deadline_s) == (True, 60)
    assert request.context == run_context(evaluation, (candidate,))
    assert len(request.client_key) == 32


@pytest.mark.parametrize(
    "context",
    [
        "not json",
        "[]",
        json.dumps({"schema": "something.else"}),
        json.dumps({"schema": "screamingface.run-context.v1"}),
    ],
    ids=["text", "array", "schema", "fields"],
)
def test_a_context_this_client_cannot_read_is_refused(context: str) -> None:
    with pytest.raises(ExecutionError) as raised:
        evaluation_from_context(context, (start_request(_candidate()),))

    assert raised.value.code == "run_context_invalid"


def test_a_context_with_a_different_number_of_candidates_is_refused() -> None:
    candidate = _candidate()
    context = run_context(_evaluation(candidate), (candidate,))

    with pytest.raises(ExecutionError) as raised:
        evaluation_from_context(context, (start_request(candidate), start_request(candidate)))

    assert raised.value.code == "run_context_invalid"
