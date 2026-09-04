from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any, NoReturn, cast

import pytest
from _evaluation_diagnostic_fixtures import (
    RESOURCE as _RESOURCE,
)
from _evaluation_diagnostic_fixtures import (
    AsyncFailingTransport as _AsyncFailingTransport,
)
from _evaluation_diagnostic_fixtures import (
    FailingTransport as _FailingTransport,
)
from _evaluation_diagnostic_fixtures import (
    SuccessfulTransport as _SuccessfulTransport,
)
from _evaluation_diagnostic_fixtures import (
    candidate as _candidate,
)
from _evaluation_diagnostic_fixtures import (
    load_benchmark as _load_benchmark,
)
from _evaluation_diagnostic_fixtures import (
    load_catalog as _load_catalog,
)
from _evaluation_diagnostic_fixtures import (
    load_details as _load_details,
)

import screamingface as sf
from screamingface._diagnostics.evaluation import _EvaluationDiagnostic
from screamingface._diagnostics.store import _STORE
from screamingface._evaluation.compilation import compile_evaluation
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.runner import evaluate_sync
from screamingface._evaluation.url4 import evaluate_url4_async, evaluate_url4_sync
from screamingface.errors import ExecutionError


@pytest.fixture(autouse=True)
def _empty_diagnostics() -> Generator[None, None, None]:
    _STORE.clear()
    yield
    _STORE.clear()


@pytest.mark.parametrize("method", ["compiled", "validated"])
def test_diagnostic_enrichment_failure_does_not_abort_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    operation_error = ExecutionError("Original operation failure.", code="original")

    def fail_enrichment(*values: object) -> NoReturn:
        del values
        raise RuntimeError("diagnostic enrichment failed")

    monkeypatch.setattr(_EvaluationDiagnostic, method, fail_enrichment)

    with pytest.raises(ExecutionError) as caught:
        evaluate_sync(
            _load_benchmark,
            _FailingTransport(operation_error),
            _load_catalog,
            _load_details,
            _candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is operation_error


def test_diagnostic_setup_failure_does_not_abort_recipe_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_setup(*values: object, **named: object) -> NoReturn:
        del values, named
        raise RuntimeError("diagnostic setup failed")

    monkeypatch.setattr(_EvaluationDiagnostic, "__init__", fail_setup)

    report = evaluate_sync(
        _load_benchmark,
        _SuccessfulTransport(),
        _load_catalog,
        _load_details,
        _candidate(),
        "draco",
        1,
        None,
        False,
        engine_url="https://engine.example",
    )

    assert report.candidates[0].score == 1.0
    assert sf.diagnostics.last() is None


def test_diagnostic_setup_failure_does_not_abort_url4_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay_url4 = compile_evaluation((_candidate(),), _RESOURCE, 1).candidates[0].url4

    def fail_setup(*values: object, **named: object) -> NoReturn:
        del values, named
        raise RuntimeError("diagnostic setup failed")

    monkeypatch.setattr(_EvaluationDiagnostic, "__init__", fail_setup)

    report = evaluate_url4_sync(
        _SuccessfulTransport(),
        replay_url4,
        None,
        None,
        None,
        False,
        engine_url="https://engine.example",
    )

    assert report.candidates[0].score == 1.0
    assert sf.diagnostics.last() is None


def test_unpresentable_terminal_guidance_is_not_retained() -> None:
    operation_error = ExecutionError("Original operation failure.", code="original")
    cast(Any, operation_error).__notes__ = ()

    with pytest.raises(ExecutionError) as caught:
        evaluate_sync(
            _load_benchmark,
            _FailingTransport(operation_error),
            _load_catalog,
            _load_details,
            _candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is operation_error
    assert sf.diagnostics.last() is None


class _ImmediateFailureTransport(_FailingTransport):
    def run(self, candidate: Candidate, on_event: object) -> NoReturn:
        del candidate, on_event
        raise self.error


class _ImmediateAsyncFailureTransport(_AsyncFailingTransport):
    async def run(self, candidate: Candidate, on_event: object) -> NoReturn:
        del candidate, on_event
        raise self.error


def test_url4_interruption_retains_known_running_candidate() -> None:
    interruption = KeyboardInterrupt()
    replay_url4 = compile_evaluation((_candidate(),), _RESOURCE, 1).candidates[0].url4

    with pytest.raises(KeyboardInterrupt) as caught:
        evaluate_url4_sync(
            _ImmediateFailureTransport(interruption),
            replay_url4,
            None,
            None,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is interruption
    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.to_dict()["executions"] == [{"candidate": "opus", "status": "running"}]


@pytest.mark.asyncio
async def test_async_url4_cancellation_retains_known_running_candidate() -> None:
    cancellation = asyncio.CancelledError()
    replay_url4 = compile_evaluation((_candidate(),), _RESOURCE, 1).candidates[0].url4

    with pytest.raises(asyncio.CancelledError) as caught:
        await evaluate_url4_async(
            _ImmediateAsyncFailureTransport(cancellation),
            replay_url4,
            None,
            None,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is cancellation
    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.to_dict()["executions"] == [{"candidate": "opus", "status": "running"}]
