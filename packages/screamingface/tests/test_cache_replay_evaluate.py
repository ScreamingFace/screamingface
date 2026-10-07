"""A replay run reaches the transport as an internal Candidate field (E14 B5, R1, R20, R24).

FEATURE: OME-1307 — `evaluate_url4_*` takes an internal `cache_replay` label and stamps it on the
Candidate, as it does the answer seed. `Client.evaluate` has no such parameter: replay is reached
only through `reproduce`.
STORY: as someone who reproduces a score, the run uses the score's own url4 and seed, and a replay
summary that does not name the label I sent is a replay the Engine did not honour.
"""

from __future__ import annotations

import inspect
from dataclasses import replace

import httpx
import pytest
from test_client_run import REPLAY_URL4, _AsyncReplayTransport, _engine, _ReplayTransport

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.url4 import evaluate_url4_async, evaluate_url4_sync
from screamingface.errors import ExecutionError

LABEL = "cr-0123456789ab"
OTHER = "cr-ba9876543210"


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


def test_the_candidate_carries_the_label_and_the_seed_to_the_transport() -> None:
    transport = _Honouring(cache_replay=LABEL)

    evaluate_url4_sync(transport, REPLAY_URL4, None, False, answer_seed=7, cache_replay=LABEL)

    assert transport.candidate is not None
    assert transport.candidate.cache_replay == LABEL
    assert transport.candidate.answer_seed == 7
    assert transport.candidate.url4 == REPLAY_URL4


def test_a_normal_evaluation_leaves_the_label_unset() -> None:
    transport = _ReplayTransport()

    evaluate_url4_sync(transport, REPLAY_URL4, None, False, answer_seed=7)

    assert transport.candidate is not None
    assert transport.candidate.cache_replay is None
    assert transport.candidate.answer_seed == 7


def test_the_seed_survives_when_the_label_is_stamped_after_it() -> None:
    transport = _Honouring(cache_replay=LABEL)

    evaluate_url4_sync(transport, REPLAY_URL4, None, False, cache_replay=LABEL)

    assert transport.candidate is not None
    assert transport.candidate.answer_seed is None


@pytest.mark.parametrize("stated", [None, OTHER])
def test_a_replay_summary_that_does_not_name_the_label_is_unsupported(stated: str | None) -> None:
    # The Engine states `cache.replay` only when it honoured the label. A summary without it, or
    # with another one, is a run that may have paid providers.
    transport = _Honouring(cache_replay=stated)

    with pytest.raises(ExecutionError) as raised:
        evaluate_url4_sync(transport, REPLAY_URL4, None, False, cache_replay=LABEL)

    assert raised.value.code == "replay_unsupported"


def test_a_normal_run_needs_no_replay_statement() -> None:
    report = evaluate_url4_sync(_ReplayTransport(), REPLAY_URL4, None, False)

    assert len(report.candidates) == 1


@pytest.mark.asyncio
async def test_the_async_twin_stamps_and_checks_the_label() -> None:
    transport = _AsyncHonouring(cache_replay=LABEL)
    report = await evaluate_url4_async(
        transport, REPLAY_URL4, None, False, answer_seed=7, cache_replay=LABEL
    )

    assert transport.candidate is not None
    assert (transport.candidate.cache_replay, transport.candidate.answer_seed) == (LABEL, 7)
    assert len(report.candidates) == 1

    with pytest.raises(ExecutionError) as raised:
        await evaluate_url4_async(_AsyncHonouring(), REPLAY_URL4, None, False, cache_replay=LABEL)
    assert raised.value.code == "replay_unsupported"


def test_evaluate_has_no_public_cache_replay_parameter() -> None:
    # Out of scope for the PRD: replay is reached only through `reproduce`.
    for target in (sf.Client.evaluate, sf.AsyncClient.evaluate, sf.evaluate):
        assert "cache_replay" not in inspect.signature(target).parameters


def test_the_client_still_runs_a_url4_the_normal_way() -> None:
    transport = _ReplayTransport()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    ) as client:
        client.evaluate(REPLAY_URL4, progress=False)

    assert transport.candidate is not None
    assert transport.candidate.cache_replay is None
