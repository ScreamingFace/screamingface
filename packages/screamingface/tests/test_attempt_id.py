"""`CandidateResult.attempt_id`, and the deprecated `run_id` (E5 P1 spec D10; plan C4).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, `report.run_id` names my
evaluation's Run, and each Candidate's own attempt is `attempt_id`; notebooks that still read
`candidate.run_id` keep working, with a warning.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import fields

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport
from test_report import candidate, report

import screamingface as sf


def _opus() -> sf.CandidateResult:
    """The fixture Candidate, built with `attempt_id` whatever the shared fixture passes."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        source = candidate("opus")
    values = {field.name: getattr(source, field.name) for field in fields(source)}
    for private in ("_metric_items", "_scores"):
        values.pop(private)
    values.update(metrics=source.metrics, scores=source.scores)
    return sf.CandidateResult(**values)


def test_attempt_id_is_the_candidates_attempt() -> None:
    value = _opus()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert value.attempt_id == "run_opus"
        assert "attempt_id" in {field.name for field in fields(value)}


def test_run_id_warns_and_equals_attempt_id() -> None:
    value = _opus()

    with pytest.warns(DeprecationWarning, match="attempt_id") as caught:
        assert value.run_id == value.attempt_id

    # The warning names the reader, so the SDK's own readers fail its tests (pyproject
    # `error::DeprecationWarning:screamingface`) while a notebook's only warn.
    assert caught[0].filename == __file__


def test_the_run_id_keyword_still_constructs_with_a_warning() -> None:
    source = candidate("opus")
    values = {field.name: getattr(source, field.name) for field in fields(source)}
    for private in ("_metric_items", "_scores"):
        values.pop(private)
    values.update(metrics=source.metrics, scores=source.scores, run_id="run_renamed")

    with pytest.warns(DeprecationWarning) as caught:
        renamed = sf.CandidateResult(**values)

    assert renamed.attempt_id == "run_renamed"
    assert caught[0].filename == __file__


def test_an_attempt_id_is_required() -> None:
    source = candidate("opus")
    values = {field.name: getattr(source, field.name) for field in fields(source)}
    for private in ("_metric_items", "_scores", "attempt_id"):
        values.pop(private)
    values.update(metrics=source.metrics, scores=source.scores)

    with pytest.raises(TypeError, match="attempt_id"):
        sf.CandidateResult(**values)


def test_saved_reports_keep_the_run_id_key() -> None:
    saved = report(_opus())

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        exported = json.loads(saved.to_json())

    assert exported["candidates"][0]["run_id"] == "run_opus"
    assert "attempt_id" not in exported["candidates"][0]


def test_a_decoded_result_carries_its_attempt() -> None:
    # WHY this path: a saved report is decoded from its stored outcome the same way.
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=_ReplayTransport(),
    ) as client:
        result = client.evaluate(REPLAY_URL4, progress=False)

    assert result.candidates[0].attempt_id == "replay-run"


def test_a_replay_report_keeps_its_run() -> None:
    from screamingface._replay import _with_reproduction

    saved = report(_opus())
    named = type(saved)(
        benchmark=saved.benchmark,
        case_count=saved.case_count,
        candidates=saved.candidates,
        run_id="run_" + "e" * 32,
    )

    assert _with_reproduction(named, None).run_id == "run_" + "e" * 32
