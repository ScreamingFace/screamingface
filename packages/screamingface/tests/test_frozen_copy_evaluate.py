"""`capture=True` and a replay reach the transport as Candidate fields (E14 B5, design §5.1, §7).

FEATURE: OME-1307 — `evaluate(..., capture=True)` stamps the request on every compiled Candidate,
as it does the answer seed. `evaluate_url4_*` also takes an internal `replay_frozen_copy` id and
stamps it. `Client.evaluate` has no such parameter: replay is reached only through `reproduce`, and
the two modes are mutually exclusive.
STORY: as someone who captures a run, `capture=True` asks the Engine for a frozen copy of every
Candidate. As someone who reproduces a score, the run uses the score's own url4 and seed, and a
replay summary that does not name the copy I sent is a replay the Engine did not honour.
"""

from __future__ import annotations

import inspect
import warnings
from dataclasses import replace
from typing import Any

import httpx
import pytest
from test_answer_seed_report import _CandidateRecordingTransport
from test_client_run import REPLAY_URL4, _AsyncReplayTransport, _engine, _ReplayTransport
from test_draco_vertical_slice import _AsyncFakeTransport
from test_draco_vertical_slice import _engine as _draco_engine

import screamingface as sf
from screamingface import _default_client
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import (
    _with_answer_seed,
    _with_capture,
    _with_replay_frozen_copy,
)
from screamingface._evaluation.url4 import evaluate_url4_async, evaluate_url4_sync
from screamingface.errors import ExecutionError

COPY = "0b1f6d3a-5c0e-4a8e-9a3f-2f6f8f4c7d11"
OTHER = "5e2a9c47-1d3b-4f60-8a7e-9c1b2d3e4f50"


class _Honouring(_ReplayTransport):
    def __init__(self, **fields: object) -> None:
        super().__init__()
        self._fields = fields

    def run(self, candidate: object, on_event: object) -> _RunOutcome:
        return replace(super().run(candidate, on_event), **self._fields)  # type: ignore[arg-type]


class _AsyncHonouring(_AsyncReplayTransport):
    def __init__(self, **fields: object) -> None:
        super().__init__()
        self._fields = fields

    async def run(self, candidate: object, on_event: object) -> _RunOutcome:
        return replace(await super().run(candidate, on_event), **self._fields)  # type: ignore[arg-type]


# --- capture=True ---------------------------------------------------------------------------------


def _captured(**fields: object) -> _Honouring:
    """A transport whose run summary states a complete capture, as an honouring Engine's does."""
    return _Honouring(frozen_copy_id=COPY, capture_status="complete", **fields)


def test_capture_is_stamped_on_the_candidate_beside_the_seed() -> None:
    transport = _captured()

    evaluate_url4_sync(transport, REPLAY_URL4, None, False, answer_seed=7, capture=True)

    assert transport.candidate is not None
    assert transport.candidate.capture is True
    assert transport.candidate.replay_frozen_copy is None
    assert transport.candidate.answer_seed == 7


def test_capture_false_leaves_capture_and_replay_unset() -> None:
    transport = _ReplayTransport()

    evaluate_url4_sync(transport, REPLAY_URL4, None, False, answer_seed=7, capture=False)

    assert transport.candidate is not None
    assert transport.candidate.capture is False
    assert transport.candidate.replay_frozen_copy is None
    assert transport.candidate.answer_seed == 7


def test_the_client_threads_capture_to_the_transport() -> None:
    transport = _captured()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    ) as client:
        (result,) = client.evaluate(REPLAY_URL4, progress=False, capture=True).candidates

    assert transport.candidate is not None
    assert transport.candidate.capture is True
    assert (result.frozen_copy_id, result.capture_status) == (COPY, "complete")


def test_the_client_captures_by_default() -> None:
    transport = _ReplayTransport()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    ) as client:
        with pytest.warns(sf.EvaluationWarning, match="did not capture"):
            client.evaluate(REPLAY_URL4, progress=False)

    assert transport.candidate is not None
    assert transport.candidate.capture is True
    assert transport.candidate.replay_frozen_copy is None


def test_capture_false_sends_no_capture_header() -> None:
    transport = _ReplayTransport()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    ) as client:
        client.evaluate(REPLAY_URL4, progress=False, capture=False)

    assert transport.candidate is not None
    assert transport.candidate.capture is False


@pytest.mark.asyncio
async def test_the_async_client_threads_capture_to_the_transport() -> None:
    transport = _AsyncHonouring(frozen_copy_id=COPY, capture_status="complete")
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    )

    await client.evaluate(REPLAY_URL4, progress=False, capture=True)
    await client.aclose()

    assert transport.candidate is not None
    assert transport.candidate.capture is True


def test_recipe_evaluation_stamps_capture_on_every_compiled_candidate() -> None:
    # The Recipe path is a different branch from the url4 path (the runner stamps, once).
    transport = _CandidateRecordingTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_draco_engine),
        run_transport=transport,
    )

    with client:
        client.evaluate(
            sf.Model("anthropic/claude-haiku-4-5", name="haiku"),
            benchmark="draco",
            limit=1,
            capture=False,
        )
        with pytest.warns(sf.EvaluationWarning, match="did not capture"):
            client.evaluate(
                sf.Model("anthropic/claude-haiku-4-5", name="haiku"),
                benchmark="draco",
                limit=1,
                capture=True,
            )

    assert [candidate.capture for candidate in transport.candidates] == [False, True]


class _AsyncCandidateRecording(_AsyncFakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[Any] = []

    async def run(self, candidate: Any, on_event: object) -> _RunOutcome:
        self.candidates.append(candidate)
        return await super().run(candidate, on_event)


@pytest.mark.asyncio
async def test_the_async_recipe_path_stamps_capture_on_every_compiled_candidate() -> None:
    transport = _AsyncCandidateRecording()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_draco_engine),
        run_transport=transport,
    )

    async with client:
        await client.evaluate(
            sf.Model("anthropic/claude-haiku-4-5", name="haiku"),
            benchmark="draco",
            limit=1,
            capture=False,
        )
        with pytest.warns(sf.EvaluationWarning, match="did not capture"):
            await client.evaluate(
                sf.Model("anthropic/claude-haiku-4-5", name="haiku"),
                benchmark="draco",
                limit=1,
                capture=True,
            )

    assert [candidate.capture for candidate in transport.candidates] == [False, True]


@pytest.mark.parametrize("target", [sf.Client.evaluate, sf.AsyncClient.evaluate, sf.evaluate])
def test_every_evaluate_door_takes_capture_and_none_takes_a_replay(target: object) -> None:
    parameters = inspect.signature(target).parameters  # type: ignore[arg-type]

    assert parameters["capture"].default is True
    assert "replay_frozen_copy" not in parameters
    assert "frozen_copy_id" not in parameters


class _RecordingDefaultClient:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def evaluate(self, *args: object, **kwargs: object) -> str:
        self.calls.append((args, kwargs))
        return "report"


@pytest.mark.parametrize("capture", [True, False])
def test_module_level_evaluate_forwards_capture_on_both_branches(
    monkeypatch: pytest.MonkeyPatch, capture: bool
) -> None:
    # INVARIANT: `sf.evaluate` is a pass-through; removing the forwarding on either branch (a
    # complete URL4, or Recipes with a benchmark) must fail here.
    fake = _RecordingDefaultClient()
    monkeypatch.setattr(_default_client, "default_client", lambda: fake)

    sf.evaluate(REPLAY_URL4, capture=capture)
    sf.evaluate(sf.Model("provider/opus"), benchmark="draco", capture=capture)

    assert [kwargs["capture"] for _, kwargs in fake.calls] == [capture, capture]


def test_module_level_evaluate_captures_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _RecordingDefaultClient()
    monkeypatch.setattr(_default_client, "default_client", lambda: fake)

    sf.evaluate(REPLAY_URL4)
    sf.evaluate(sf.Model("provider/opus"), benchmark="draco")

    assert [kwargs["capture"] for _, kwargs in fake.calls] == [True, True]


# --- a capture the Engine did not make ------------------------------------------------------------


def test_capture_without_a_capture_status_warns_and_keeps_the_fields_none() -> None:
    # An Engine that ignores `X-Capture` runs the Candidate normally: no `capture.status`.
    with pytest.warns(sf.EvaluationWarning, match="did not capture this run") as caught:
        report = evaluate_url4_sync(_ReplayTransport(), REPLAY_URL4, None, False, capture=True)

    (result,) = report.candidates
    assert (result.frozen_copy_id, result.capture_status) == (None, None)
    assert "it cannot be reproduced" in str(caught[0].message)
    assert result.name in str(caught[0].message)


@pytest.mark.asyncio
async def test_the_async_path_warns_too() -> None:
    with pytest.warns(sf.EvaluationWarning, match="did not capture this run"):
        await evaluate_url4_async(_AsyncReplayTransport(), REPLAY_URL4, None, False, capture=True)


@pytest.mark.parametrize(
    "fields",
    [
        {"frozen_copy_id": COPY, "capture_status": "complete"},
        # A copy that failed to open: the Engine stated a status, so it did capture (partially).
        {"frozen_copy_id": None, "capture_status": "partial"},
    ],
)
def test_a_stated_capture_status_raises_no_warning(fields: dict[str, object]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        evaluate_url4_sync(_Honouring(**fields), REPLAY_URL4, None, False, capture=True)


def test_a_run_that_did_not_ask_for_capture_raises_no_capture_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        evaluate_url4_sync(_ReplayTransport(), REPLAY_URL4, None, False)


def test_capture_and_a_replay_are_mutually_exclusive() -> None:
    # INVARIANT: no stamp can build a Candidate that asks the Engine for both (it answers 400).
    transport = _ReplayTransport()

    with pytest.raises(ValueError, match="mutually exclusive"):
        evaluate_url4_sync(
            transport, REPLAY_URL4, None, False, capture=True, replay_frozen_copy=COPY
        )

    assert transport.candidate is None


# --- the replay copy ------------------------------------------------------------------------------


def test_the_candidate_carries_the_copy_and_the_seed_to_the_transport() -> None:
    transport = _Honouring(capture_replay=COPY)

    evaluate_url4_sync(transport, REPLAY_URL4, None, False, answer_seed=7, replay_frozen_copy=COPY)

    assert transport.candidate is not None
    assert transport.candidate.replay_frozen_copy == COPY
    assert transport.candidate.capture is False
    assert transport.candidate.answer_seed == 7
    assert transport.candidate.url4 == REPLAY_URL4


def test_the_stamps_keep_each_other_in_either_order() -> None:
    transport = _ReplayTransport()
    evaluate_url4_sync(transport, REPLAY_URL4, None, False)
    assert transport.candidate is not None

    seeded = _with_answer_seed(transport.candidate, 7)
    assert _with_replay_frozen_copy(seeded, COPY).answer_seed == 7
    assert _with_capture(seeded).answer_seed == 7
    assert _with_capture(seeded).url4 == seeded.url4
    assert _with_answer_seed(_with_capture(transport.candidate), 7).capture is True


@pytest.mark.parametrize("stated", [None, OTHER])
def test_a_replay_summary_that_does_not_name_the_copy_is_unsupported(stated: str | None) -> None:
    # The Engine states `capture.replay` only when it honoured the copy. A summary without it, or
    # with another one, is a run that may have paid providers.
    transport = _Honouring(capture_replay=stated)

    with pytest.raises(ExecutionError) as raised:
        evaluate_url4_sync(transport, REPLAY_URL4, None, False, replay_frozen_copy=COPY)

    assert raised.value.code == "replay_unsupported"


def test_a_normal_run_needs_no_replay_statement() -> None:
    report = evaluate_url4_sync(_ReplayTransport(), REPLAY_URL4, None, False)

    assert len(report.candidates) == 1


@pytest.mark.asyncio
async def test_the_async_twin_stamps_and_checks_the_copy() -> None:
    transport = _AsyncHonouring(capture_replay=COPY)
    report = await evaluate_url4_async(
        transport, REPLAY_URL4, None, False, answer_seed=7, replay_frozen_copy=COPY
    )

    assert transport.candidate is not None
    assert (transport.candidate.replay_frozen_copy, transport.candidate.answer_seed) == (COPY, 7)
    assert len(report.candidates) == 1

    with pytest.raises(ExecutionError) as raised:
        await evaluate_url4_async(
            _AsyncHonouring(), REPLAY_URL4, None, False, replay_frozen_copy=COPY
        )
    assert raised.value.code == "replay_unsupported"

    capture_transport = _AsyncHonouring(frozen_copy_id=COPY, capture_status="complete")
    await evaluate_url4_async(capture_transport, REPLAY_URL4, None, False, capture=True)
    assert capture_transport.candidate is not None
    assert capture_transport.candidate.capture is True
