from __future__ import annotations

import sys
from datetime import UTC, datetime
from io import StringIO
from typing import Any, cast

import pytest

import screamingface as sf
from screamingface._evaluation.observers import (
    _async_event_observer,
    _close_event_observer,
    _sync_event_observer,
)
from screamingface._evaluation.progress import _message, _progress_observer


def envelope() -> dict[str, Any]:
    return {
        "id": "event_1",
        "run_id": "run_1",
        "sequence": 1,
        "timestamp": datetime(2026, 7, 25, 16, 0, tzinfo=UTC),
        "source": "/trace/run_1/node/root",
    }


def test_progress_can_be_disabled_or_forced() -> None:
    stream = StringIO()

    assert _progress_observer(False, stream=stream) is None
    observer = _progress_observer(True, stream=stream)
    assert observer is not None

    observer.observe(
        cast(Any, object()),
        sf.events.Started(**envelope(), url4="(@)!'hello'"),
    )

    assert stream.getvalue() == "ScreamingFace · Evaluation started\n"


def test_progress_defaults_on_inside_a_notebook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "ipykernel", object())

    assert _progress_observer(None, stream=StringIO()) is not None


def test_progress_messages_cover_meaningful_lifecycle_events() -> None:
    log = sf.events.Log(
        **envelope(),
        severity_number=9,
        severity_text="INFO",
        body="Grading case 1",
    )
    terminated = sf.events.Terminated(**envelope(), status="timed_out")
    usage = sf.events.Usage(
        **envelope(),
        scope="subtree",
        provider="openrouter",
        model="model",
        pricing_version="v1",
    )

    assert _message(log) == "Grading case 1"
    assert _message(terminated) == "Evaluation timed out"
    assert _message(usage) is None


def test_successful_evaluation_uses_finished_as_its_public_terminal_wording() -> None:
    terminated = sf.events.Terminated(**envelope(), status="succeeded")

    assert _message(terminated) == "Evaluation finished"


def test_progress_neutralizes_terminal_controls_and_multiline_log_spoofing() -> None:
    stream = StringIO()
    observer = _progress_observer(True, stream=stream)
    assert observer is not None

    observer.observe(
        cast(Any, object()),
        sf.events.Log(
            **envelope(),
            severity_number=9,
            severity_text="INFO",
            body="safe\x1b]0;forged-title\x07\rforged\nnext\tline",
        ),
    )

    assert stream.getvalue() == ("ScreamingFace · safe ]0;forged-title forged next line\n")


def test_progress_hides_structural_spans_and_summarizes_model_completions() -> None:
    started = datetime(2026, 7, 25, 16, 0, tzinfo=UTC)
    structural = sf.events.Span(
        **envelope(),
        name="TextNode",
        operation="TextNode",
        start=started,
        end=started,
    )
    model = sf.events.Span(
        **envelope(),
        name="RelUrlNode",
        operation="RelUrlNode",
        start=started,
        end=datetime(2026, 7, 25, 16, 0, 4, 800000, tzinfo=UTC),
        provider="openrouter",
        request_model="openrouter/anthropic/claude-haiku-4.5",
        input_tokens=103,
        output_tokens=374,
        finish_reasons=("stop",),
    )

    assert _message(structural) is None
    assert _message(model) == (
        "Model completed · openrouter/anthropic/claude-haiku-4.5 · 4.8s · 103 in / 374 out · stop"
    )


def test_sync_evaluate_combines_builtin_and_caller_observers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str]] = []

    class Progress:
        def observe(self, candidate: object, event: sf.Event) -> None:
            del candidate
            observed.append(("progress", event.kind))

    monkeypatch.setattr(
        "screamingface._evaluation.progress._progress_observer",
        lambda requested, **_: Progress(),
    )
    callback = _sync_event_observer(
        lambda event: observed.append(("caller", event.kind)),
        True,
    )
    assert callback is not None

    callback.bind(cast(Any, object()))(sf.events.Started(**envelope(), url4="(@)!'hello'"))

    assert observed == [("progress", "started"), ("caller", "started")]


def test_sync_builtin_progress_failure_does_not_block_the_caller_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    class BrokenProgress:
        def observe(self, candidate: object, event: sf.Event) -> None:
            del candidate, event
            raise OSError("stdout closed")

    monkeypatch.setattr(
        "screamingface._evaluation.progress._progress_observer",
        lambda requested, **_: BrokenProgress(),
    )
    callback = _sync_event_observer(lambda event: observed.append(event.kind), True)
    assert callback is not None

    callback.bind(cast(Any, object()))(sf.events.Started(**envelope(), url4="(@)!'hello'"))

    assert observed == ["started"]


def test_sync_evaluation_failure_closes_live_builtin_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Progress:
        closed = False

        def observe(self, candidate: object, event: sf.Event) -> None:
            del candidate, event

        def close(self) -> None:
            self.closed = True

    progress = Progress()
    monkeypatch.setattr(
        "screamingface._evaluation.progress._progress_observer",
        lambda requested, **_: progress,
    )
    observer = _sync_event_observer(None, True)

    _close_event_observer(observer)

    assert progress.closed is True


@pytest.mark.asyncio
async def test_async_evaluate_combines_builtin_and_async_caller_observers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str]] = []

    class Progress:
        def observe(self, candidate: object, event: sf.Event) -> None:
            del candidate
            observed.append(("progress", event.kind))

    monkeypatch.setattr(
        "screamingface._evaluation.progress._progress_observer",
        lambda requested, **_: Progress(),
    )

    async def caller(event: sf.Event) -> None:
        observed.append(("caller", event.kind))

    callback = _async_event_observer(caller, True)
    assert callback is not None

    await callback.bind(cast(Any, object()))(sf.events.Started(**envelope(), url4="(@)!'hello'"))

    assert observed == [("progress", "started"), ("caller", "started")]


@pytest.mark.asyncio
async def test_async_builtin_progress_failure_does_not_block_the_caller_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    class BrokenProgress:
        def observe(self, candidate: object, event: sf.Event) -> None:
            del candidate, event
            raise OSError("stdout closed")

    monkeypatch.setattr(
        "screamingface._evaluation.progress._progress_observer",
        lambda requested, **_: BrokenProgress(),
    )

    async def caller(event: sf.Event) -> None:
        observed.append(event.kind)

    callback = _async_event_observer(caller, True)
    assert callback is not None

    await callback.bind(cast(Any, object()))(sf.events.Started(**envelope(), url4="(@)!'hello'"))

    assert observed == ["started"]


@pytest.mark.asyncio
async def test_async_evaluation_failure_closes_live_builtin_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Progress:
        closed = False

        def observe(self, candidate: object, event: sf.Event) -> None:
            del candidate, event

        def close(self) -> None:
            self.closed = True

    progress = Progress()
    monkeypatch.setattr(
        "screamingface._evaluation.progress._progress_observer",
        lambda requested, **_: progress,
    )
    observer = _async_event_observer(None, True)

    _close_event_observer(observer)

    assert progress.closed is True


def test_candidate_identity_and_case_count_reach_builtin_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    def progress_observer(requested: bool | None, **context: object):
        received.update(context)
        return lambda _event: None

    monkeypatch.setattr(
        "screamingface._evaluation.progress._progress_observer",
        progress_observer,
    )

    candidates = (object(),)
    observer = _sync_event_observer(
        None,
        True,
        candidates=cast(Any, candidates),
        case_count=100,
        benchmark="draco",
    )

    assert observer is not None
    assert received["candidates"] == candidates
    assert received["case_count"] == 100
