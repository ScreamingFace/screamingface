from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any, NoReturn, cast

import _evaluation_diagnostic_fixtures as _fixtures
import pytest

import screamingface as sf
from screamingface._diagnostics.store import _STORE
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.runner import evaluate_async, evaluate_sync
from screamingface._evaluation.url4 import evaluate_url4_sync
from screamingface.errors import ExecutionError


@pytest.fixture(autouse=True)
def _empty_diagnostics() -> Generator[None, None, None]:
    _STORE.clear()
    yield
    _STORE.clear()


def test_sync_evaluation_failure_stages_one_receipt_and_preserves_exception() -> None:
    error = ExecutionError(
        "The Engine disconnected.",
        code="websocket_disconnected",
        permanent=False,
    )

    with pytest.raises(ExecutionError) as caught:
        evaluate_sync(
            _fixtures.load_benchmark,
            _fixtures.FailingTransport(error),
            _fixtures.load_catalog,
            _fixtures.load_details,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://user:secret@engine.example/private?token=secret",
        )

    assert caught.value is error
    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert error.__notes__ == [
        f"Diagnostic: {receipt.diagnostic_id}. Export with "
        f'sf.diagnostics.get("{receipt.diagnostic_id}").export('
        '"screamingface-diagnostic.json")'
    ]
    assert error.__notes__[0] in error._render_traceback_()[0]
    document = receipt.to_dict()
    assert document["operation"] == "evaluate"
    assert document["outcome"] == "failed"
    assert isinstance(document["elapsed_seconds"], float)
    assert document["elapsed_seconds"] >= 0
    assert document["context"]["engine"] == {"host": "engine.example", "mode": "hosted"}
    assert document["context"]["benchmark"] == {
        "id": "draco",
        "revision": "fixture-revision",
        "case_count": 1,
    }
    assert document["context"]["candidates"][0]["parameters"] == [
        {
            "operation_id": "op_model_1",
            "model": "provider/opus",
            "values": {"max_tokens": 64},
        }
    ]
    assert document["executions"] == [
        {
            "candidate": "opus",
            "status": "running",
            "trace_id": _fixtures.TRACE_ID,
        }
    ]
    encoded = receipt.to_json()
    assert "internal-stream-topic" not in encoded
    assert "private answer instruction" not in encoded
    assert "user:secret" not in encoded
    assert "token=secret" not in encoded


def test_plain_argument_error_stages_a_degraded_receipt() -> None:
    with pytest.raises(TypeError) as caught:
        evaluate_sync(
            _fixtures.load_benchmark,
            _fixtures.FailingTransport(AssertionError("transport must not run")),
            _fixtures.load_catalog,
            _fixtures.load_details,
            cast(Any, object()),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    receipt = sf.diagnostics.last()
    assert receipt is not None
    error = receipt.to_dict()["error"]
    assert error["type"] == "TypeError"
    assert "code" not in error
    assert "message" not in error
    assert receipt.diagnostic_id in caught.value.__notes__[0]


def test_public_client_input_validation_stages_a_degraded_receipt() -> None:
    with sf.Client(
        engine_url="https://engine.example",
        run_transport=_fixtures.FailingTransport(AssertionError("transport must not run")),
    ) as client:
        with pytest.raises(TypeError, match="benchmark is required"):
            cast(Any, client).evaluate(_fixtures.candidate())

    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.to_dict()["error"]["type"] == "TypeError"


@pytest.mark.parametrize(
    ("option", "message"),
    [
        ({"benchmark": "draco"}, "benchmark must not be passed"),
        ({"limit": 1}, "limit must not be passed"),
    ],
)
def test_public_url4_option_validation_stages_a_degraded_receipt(
    option: dict[str, object],
    message: str,
) -> None:
    # INVARIANT: direct URL4 replay owns the same diagnostic boundary as Recipe evaluation.
    with sf.Client(
        engine_url="https://engine.example",
        run_transport=_fixtures.FailingTransport(AssertionError("transport must not run")),
    ) as client:
        with pytest.raises(TypeError, match=message) as caught:
            cast(Any, client).evaluate("(@)!'hello'", **option)

    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.to_dict()["error"]["type"] == "TypeError"
    assert receipt.diagnostic_id in caught.value.__notes__[0]


def test_preparation_failure_retains_safe_caller_candidate_identity() -> None:
    with sf.Client(
        engine_url="https://engine.example",
        run_transport=_fixtures.FailingTransport(AssertionError("transport must not run")),
    ) as client:
        with pytest.raises(TypeError, match="benchmark is required"):
            cast(Any, client).evaluate(_fixtures.candidate())

    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.to_dict()["context"]["candidates"] == [
        {
            "name": "opus",
            "kind": "model",
        }
    ]
    assert "private answer instruction" not in receipt.to_json()


def test_unvalidated_benchmark_object_is_not_captured() -> None:
    class PrivateBenchmark:
        def __repr__(self) -> str:
            return "private-benchmark-value"

    with sf.Client(
        engine_url="https://engine.example",
        run_transport=_fixtures.FailingTransport(AssertionError("transport must not run")),
    ) as client:
        with pytest.raises(ValueError, match="benchmark"):
            cast(Any, client).evaluate(_fixtures.candidate(), benchmark=PrivateBenchmark())

    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert "private-benchmark-value" not in receipt.to_json()


@pytest.mark.asyncio
async def test_async_evaluation_failure_uses_the_same_receipt_contract() -> None:
    error = ExecutionError("Async failed.", code="async_failed", permanent=True)

    with pytest.raises(ExecutionError) as caught:
        await evaluate_async(
            _fixtures.load_benchmark_async,
            _fixtures.AsyncFailingTransport(error),
            _fixtures.load_catalog_async,
            _fixtures.load_details_async,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is error
    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.to_dict()["executions"] == [
        {
            "candidate": "opus",
            "status": "running",
            "trace_id": _fixtures.TRACE_ID,
        }
    ]


def test_preparation_failure_does_not_reconstruct_composite_recipe_models() -> None:
    candidate = sf.Fusion(
        ["provider/opus", "provider/gpt"],
        synthesizer="provider/synth",
        name="panel",
    )
    with sf.Client(
        engine_url="https://engine.example",
        run_transport=_fixtures.FailingTransport(AssertionError("transport must not run")),
    ) as client:
        with pytest.raises(TypeError, match="benchmark is required"):
            cast(Any, client).evaluate(candidate)

    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.to_dict()["context"]["candidates"] == [{"name": "panel", "kind": "fusion"}]


def test_malformed_trace_context_is_not_fabricated() -> None:
    class InvalidTraceTransport(_fixtures.FailingTransport):
        def run(self, candidate: Candidate, on_event: object) -> NoReturn:
            if callable(on_event):
                on_event(_fixtures.started(candidate, traceparent="00-invalid-parent-01"))
            raise self.error

    with pytest.raises(ExecutionError):
        evaluate_sync(
            _fixtures.load_benchmark,
            InvalidTraceTransport(ExecutionError("Failed.")),
            _fixtures.load_catalog,
            _fixtures.load_details,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert "trace_id" not in receipt.to_dict()["executions"][0]


def test_breadcrumb_retains_only_relative_route_span_names() -> None:
    class SpanTransport(_fixtures.FailingTransport):
        def run(self, candidate: Candidate, on_event: object) -> NoReturn:
            assert callable(on_event)
            on_event(_fixtures.started(candidate))
            now = datetime.now(UTC)
            on_event(
                sf.events.Span(
                    id="event-2",
                    run_id="internal-stream-topic",
                    sequence=2,
                    timestamp=now,
                    source="fixture",
                    name="/benchmarks/case-execution",
                    operation="RelUrlNode",
                    start=now,
                    end=now,
                )
            )
            on_event(
                sf.events.Span(
                    id="event-3",
                    run_id="internal-stream-topic",
                    sequence=3,
                    timestamp=now,
                    source="fixture",
                    name="private prompt text",
                    operation="TextNode",
                    start=now,
                    end=now,
                )
            )
            raise self.error

    with pytest.raises(ExecutionError):
        evaluate_sync(
            _fixtures.load_benchmark,
            SpanTransport(ExecutionError("Failed.")),
            _fixtures.load_catalog,
            _fixtures.load_details,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    receipt = sf.diagnostics.last()
    assert receipt is not None
    breadcrumbs = receipt.to_dict()["breadcrumbs"]
    assert [item["operation"] for item in breadcrumbs if "operation" in item] == [
        "/benchmarks/case-execution"
    ]
    assert "private prompt text" not in receipt.to_json()


def test_url4_replay_failure_uses_the_same_diagnostic_boundary() -> None:
    from screamingface._evaluation.compilation import compile_evaluation

    error = ExecutionError("Replay failed.", code="replay_failed")
    replay_url4 = (
        compile_evaluation((_fixtures.candidate(),), _fixtures.RESOURCE, 1).candidates[0].url4
    )

    with pytest.raises(ExecutionError) as caught:
        evaluate_url4_sync(
            _fixtures.FailingTransport(error),
            replay_url4,
            None,
            None,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is error
    receipt = sf.diagnostics.last()
    assert receipt is not None
    document = receipt.to_dict()
    assert document["context"]["mode"] == "url4_replay"
    assert replay_url4 not in receipt.to_json()


def test_keyboard_interrupt_stages_observable_state_and_is_reraised() -> None:
    interruption = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt) as caught:
        evaluate_sync(
            _fixtures.load_benchmark,
            _fixtures.FailingTransport(interruption),
            _fixtures.load_catalog,
            _fixtures.load_details,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is interruption
    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.outcome == "interrupted_by_user"
    assert receipt.to_dict()["executions"][0]["status"] == "running"
    assert "hung" not in receipt.to_json().lower()


@pytest.mark.asyncio
async def test_async_cancellation_stages_cancelled_state_and_is_reraised() -> None:
    cancellation = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError) as caught:
        await evaluate_async(
            _fixtures.load_benchmark_async,
            _fixtures.AsyncFailingTransport(cancellation),
            _fixtures.load_catalog_async,
            _fixtures.load_details_async,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is cancellation
    receipt = sf.diagnostics.last()
    assert receipt is not None
    assert receipt.outcome == "cancelled"


@pytest.mark.parametrize("signal", [SystemExit(2), GeneratorExit()])
def test_process_control_exceptions_bypass_diagnostics(signal: BaseException) -> None:
    with pytest.raises(type(signal)):
        evaluate_sync(
            _fixtures.load_benchmark,
            _fixtures.FailingTransport(signal),
            _fixtures.load_catalog,
            _fixtures.load_details,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert sf.diagnostics.last() is None


def test_partial_report_with_case_failures_stages_no_diagnostic() -> None:
    report = evaluate_sync(
        _fixtures.load_benchmark,
        _fixtures.PartialTransport(),
        _fixtures.load_catalog,
        _fixtures.load_details,
        _fixtures.candidate(),
        "draco",
        1,
        None,
        False,
        engine_url="https://engine.example",
    )

    assert report.failures[0].code == "case_not_graded"
    assert sf.diagnostics.last() is None


def test_capture_failure_never_replaces_the_operation_error(monkeypatch) -> None:
    error = ExecutionError("Original failure.", code="original")

    def broken_capture(context: object, raised: BaseException) -> NoReturn:
        del context, raised
        raise RuntimeError("diagnostic capture failed")

    monkeypatch.setattr(
        "screamingface._diagnostics.evaluation._EvaluationDiagnostic.stage",
        broken_capture,
    )

    with pytest.raises(ExecutionError) as caught:
        evaluate_sync(
            _fixtures.load_benchmark,
            _fixtures.FailingTransport(error),
            _fixtures.load_catalog,
            _fixtures.load_details,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is error
    assert sf.diagnostics.last() is None


def test_diagnostic_note_failure_never_replaces_the_operation_error() -> None:
    class NoteFailure(ExecutionError):
        def add_note(self, note: str) -> None:
            del note
            raise RuntimeError("note attachment failed")

    error = NoteFailure("Original failure.", code="original")

    with pytest.raises(NoteFailure) as caught:
        evaluate_sync(
            _fixtures.load_benchmark,
            _fixtures.FailingTransport(error),
            _fixtures.load_catalog,
            _fixtures.load_details,
            _fixtures.candidate(),
            "draco",
            1,
            None,
            False,
            engine_url="https://engine.example",
        )

    assert caught.value is error
    assert sf.diagnostics.last() is not None
