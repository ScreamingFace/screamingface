"""OME-1989 — a run whose key the provider refuses stops, instead of failing every Case.

FEATURE: OME-1989. On 2026-11-19 one account's 18 runs sent 7,056 Candidate calls that the
provider refused with 403, one failed Case at a time, holding runner slots the whole time.
STORY: as an on-call engineer, a disabled key ends its runs in a handful of calls, so one
account cannot queue everyone else behind calls that were never going to answer.

INVARIANT: once the run stopped, no further Candidate call reaches the gateway, and the run ends
with one run-level ``provider_key_refused``. A 403 that belongs to one Case (a flagged input)
never stops a run on its own: only the same refusal on 5 Cases in a row does.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from frozen_copy_support import CHAT, MODEL, Gateway, chat, error, run_call

from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.request_scope import RequestScope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world import refused_key_stop as stop
from screamingface_engine.world.connector import key_refusal_as_url4_error
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node
from url4.streaming.interfaces import Completed

_RUN = RequestScope(origin="run")
_REFUSED_403 = "provider_error"  # the gateway's code for a provider 403 today


def _gateway(steps: list[httpx.Response]) -> Gateway:
    """A scripted gateway that answers the chat calls with ``steps``, in order."""
    scripted: list[httpx.Response | BaseException] = list(steps)
    return Gateway(scripted)


async def _run_cases(
    gateway: Gateway,
    case_ids: list[str | None],
    *,
    candidate: bool = True,
) -> tuple[list[str | None], ResolutionError | None]:
    """One run that makes one model call per entry of ``case_ids``, as the executor scopes it.

    Returns each call's failure code (None for an answer) and the run-level error the run's
    scope raised as it closed (None when the run was not stopped).
    """
    codes: list[str | None] = []
    run_error: ResolutionError | None = None
    try:
        # The executor's pair: the rule's scope inside, the connector's url4 translation outside.
        with key_refusal_as_url4_error(), stop.refused_key_scope():
            for case_id in case_ids:
                if not candidate:
                    _tally, _answer, failure = await run_call(gateway, _RUN, web_search=False)
                else:
                    # The scopes the Candidate adapter opens around a Case's answering calls.
                    with candidate_invocation_scope(), case_scope(case_id):
                        _tally, _answer, failure = await run_call(gateway, _RUN, web_search=False)
                codes.append(None if failure is None else failure.code)
    except ResolutionError as exc:
        run_error = exc
    return codes, run_error


def _cases(count: int) -> list[str | None]:
    """``count`` distinct Case ids."""
    return [f"case-{n}" for n in range(1, count + 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "names"),
    [(401, "auth_required", "rejected the key"), (402, "insufficient_credits", "out of credits")],
)
async def test_the_first_rejected_or_unfunded_key_stops_the_run(
    status: int, code: str, names: str
) -> None:
    gateway = _gateway([error(status, code)])

    codes, run_error = await _run_cases(gateway, _cases(4))

    # WHY 1: neither refusal can succeed on the next Case, so nothing more is sent.
    assert len(gateway.calls(CHAT)) == 1
    # The refused Case keeps its own failure; the three after it are refused by the Engine.
    assert codes == [code, stop.STOP_CODE, stop.STOP_CODE, stop.STOP_CODE]
    assert run_error is not None
    assert (run_error.code, run_error.permanent) == (stop.STOP_CODE, True)
    assert names in str(run_error) and MODEL in str(run_error)


@pytest.mark.asyncio
async def test_the_same_403_on_five_cases_in_a_row_stops_the_run() -> None:
    gateway = _gateway([error(403, _REFUSED_403)] * 100)

    codes, run_error = await _run_cases(gateway, _cases(100))

    # WHY 5 and not 100: this is the 2026-11-19 incident, cut from one call per Case to five.
    assert len(gateway.calls(CHAT)) == stop.REFUSALS_BEFORE_STOP == 5
    assert codes == [_REFUSED_403] * 5 + [stop.STOP_CODE] * 95
    assert run_error is not None and run_error.code == stop.STOP_CODE
    assert "HTTP 403 on 5 Cases in a row" in str(run_error)


@pytest.mark.asyncio
async def test_the_stop_message_never_carries_the_gateways_text() -> None:
    """The message is engine-vouched (``ENGINE_ERROR_CODES``), so upstream text must not ride it."""
    refused = httpx.Response(
        403, json={"detail": {"code": "sk-leaked-code", "message": "sk-leaked-message"}}
    )
    gateway = _gateway([refused] * 5)

    _codes, run_error = await _run_cases(gateway, _cases(5))

    assert run_error is not None
    assert "sk-leaked" not in str(run_error)


@pytest.mark.asyncio
async def test_one_answer_between_refusals_starts_the_count_over() -> None:
    refused = error(403, _REFUSED_403)
    gateway = _gateway([refused] * 4 + [chat("an answer")] + [refused] * 4)

    codes, run_error = await _run_cases(gateway, _cases(9))

    # WHY: a 403 can belong to one input (a prompt the provider's moderation flagged). A key
    # that still answers is not refused, so four flagged Cases on each side stop nothing.
    assert run_error is None
    assert len(gateway.calls(CHAT)) == 9
    assert codes == [_REFUSED_403] * 4 + [None] + [_REFUSED_403] * 4


@pytest.mark.asyncio
async def test_a_different_refusal_starts_the_count_over() -> None:
    gateway = _gateway(
        [error(403, _REFUSED_403)] * 4 + [error(403, "another_code")] * 4 + [error(400, "x")]
    )

    codes, run_error = await _run_cases(gateway, _cases(9))

    assert run_error is None
    assert len(codes) == 9 and stop.STOP_CODE not in codes


@pytest.mark.asyncio
async def test_attempts_of_one_case_count_as_one_case() -> None:
    gateway = _gateway([error(403, _REFUSED_403)] * 8)

    # WHY: a Benchmark that asks each Case several times sends the same flagged input each
    # time. Eight refused Attempts of ONE Case are one Case's failure, not a refused key.
    _codes, run_error = await _run_cases(gateway, ["case-1"] * 8)

    assert run_error is None
    assert len(gateway.calls(CHAT)) == 8


@pytest.mark.asyncio
async def test_a_judge_call_is_never_counted_or_refused() -> None:
    gateway = _gateway([error(403, _REFUSED_403)] * 8)

    # WHY: only the Candidate is the user's key. A judge call is not made inside the Candidate
    # invocation, and a judge's failure is graded by its own rules.
    codes, run_error = await _run_cases(gateway, _cases(8), candidate=False)

    assert run_error is None
    assert codes == [_REFUSED_403] * 8


@pytest.mark.asyncio
async def test_a_stopped_run_still_lets_a_judge_call_through() -> None:
    gateway = _gateway([error(402, "insufficient_credits"), chat("a verdict")])

    with pytest.raises(stop.KeyRefused), stop.refused_key_scope():
        with candidate_invocation_scope():
            await run_call(gateway, _RUN, web_search=False)
        _tally, answer, failure = await run_call(gateway, _RUN, web_search=False)
        assert failure is None and answer == "a verdict"


@pytest.mark.asyncio
async def test_one_runs_refusals_never_reach_the_next_run() -> None:
    """The state is bound per run: local mode serves every run from one process and one world."""
    first, _ = await _run_cases(_gateway([error(403, _REFUSED_403)] * 4), _cases(4))
    second, run_error = await _run_cases(_gateway([error(403, _REFUSED_403)] * 4), _cases(4))

    assert run_error is None
    assert first == second == [_REFUSED_403] * 4


@pytest.mark.asyncio
async def test_a_cancelled_run_stays_cancelled_after_a_stop() -> None:
    """A stop or deadline is its own terminal reason; the stop error must not replace it."""
    with pytest.raises(asyncio.CancelledError), stop.refused_key_scope():
        with candidate_invocation_scope():
            stop.note_refusal(MODEL, status=402, code="insufficient_credits")
        raise asyncio.CancelledError


def test_outside_a_run_nothing_is_counted_or_refused() -> None:
    """The sync surface and tests bind no run holder; the rule is then a no-op."""
    with candidate_invocation_scope():
        stop.note_refusal(MODEL, status=402, code="insufficient_credits")
        assert stop.note_answer(MODEL, "an answer") == "an answer"
        stop.refuse_if_stopped()


@pytest.mark.asyncio
async def test_an_engine_run_that_stopped_fails_instead_of_completing() -> None:
    """The executor binds the scope: a stopped run is a failed run, never a finished Report.

    WHY this matters most: url4 collects each Case's error into a row, so without the executor's
    scope a stopped run would still finish as a Report of failed Cases.
    """
    node = Url4Node("n1")
    calls: list[str] = []

    @node.endpoint("/candidate")
    def candidate(request: object) -> str:
        # Stands in for the Candidate's model call: the first one is refused for credits, as the
        # connector reports it, and any later one is refused by the Engine before it is sent.
        with candidate_invocation_scope():
            with key_refusal_as_url4_error():
                stop.refuse_if_stopped()
            calls.append("sent")
            stop.note_refusal(MODEL, status=402, code="insufficient_credits")
        raise ResolutionError("refused", code="insufficient_credits", permanent=True)

    # Three rows, each error collected into a row, the way a Benchmark runs its Cases.
    expression = '["a","b","c"]*(/candidate($item)!"i";on_error=collect)!"per"'
    steps: list[object] = []
    with pytest.raises(ResolutionError) as caught:
        async for step in Url4Executor(node).execute(expression):
            steps.append(step)

    assert (caught.value.code, caught.value.permanent) == (stop.STOP_CODE, True)
    assert not any(isinstance(step, Completed) for step in steps)
    assert calls == ["sent"]
