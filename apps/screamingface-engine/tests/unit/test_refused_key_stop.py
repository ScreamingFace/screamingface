"""OME-1989 — a run whose key the provider refuses stops, instead of failing every Case.

FEATURE: OME-1989. On 2026-11-19 one account's 18 runs sent 7,056 Candidate calls that the
provider refused with 403, one failed Case at a time, holding runner slots the whole time.
STORY: as an on-call engineer, a disabled key ends its runs in a handful of calls, so one
account cannot queue everyone else behind calls that were never going to answer.

INVARIANT: the rule judges CASES through the real Candidate adapter, never single calls. A Case
the refusal made fail (or left with no answering call) counts; a Case the Candidate still
answered (a dropped quorum member, a fallback Gate, a collected row) never does. Once the run
stopped, no further Case reaches the gateway, and the run ends with one run-level
``provider_key_refused``. A 403 on its own never stops a run: only the same refusal on 5 Cases
in a row does, because one 403 can be a single input the provider's moderation flagged.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from _signal_world import _body
from frozen_copy_support import CHAT, MODEL, error, run_call
from frozen_copy_support import Gateway as ScriptedGateway

from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.definition import candidate, link_candidate
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world import refused_key_stop as stop
from screamingface_engine.world.branch import install_branch_runtime
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import (
    AigatewayConfig,
    build_aigateway_world,
    key_refusal_as_url4_error,
)
from url4.core.errors import ResolutionError, Url4Error
from url4.dag import run as url4_run
from url4.peer.server import Request, Url4Node
from url4.streaming.interfaces import Completed

_DATA = Path(__file__).parent / "data"
_RUN = RequestScope(origin="run")
_REFUSED_403 = "provider_error"  # the gateway's code for a provider 403 today

#: A solo Candidate: one model answers each Case.
_SOLO = "/solo($input)!'Answer the request.'"
#: A quorum Fusion, the SDK's compile: members good-a and good-b required, member bad optional,
#: quorum 2, synthesiser synth.
_QUORUM = (_DATA / "fusion_quorum_candidate.url4").read_text(encoding="utf-8").strip()
#: A fallback Gate, the SDK's compile of
#: ``sf.Cascade("prov/primary", sf.escalate_if(sf.unanswered()), "prov/backup")``.
_FALLBACK = (_DATA / "gate_contract" / "fallback_unanswered.url4").read_text("utf-8").strip()
#: A row policy inside the Candidate: two rows, each row's error collected into the answer.
_ROWS = '["row-a","row-b"]*(/rows($item)!"Answer the request.";on_error=collect)!"per"'

#: A scripted reply to one model call: built at once, or (for a delayed reply) awaited.
type Reply = Callable[[dict[str, Any]], httpx.Response]
type SlowReply = Callable[[dict[str, Any]], Awaitable[httpx.Response]]


def live(content: str = "an answer") -> Reply:
    """The provider answers this call."""
    return lambda _sent: httpx.Response(
        200, headers={"X-AIGW-Cache": "miss"}, json=_body(content, "0.001", "miss")
    )


def cached(content: str = "an answer") -> Reply:
    """The gateway serves a stored reply; the provider is never asked."""
    return lambda _sent: httpx.Response(
        200, headers={"X-AIGW-Cache": "hit"}, json=_body(content, "0.001", "hit")
    )


def refused(status: int, code: str) -> Reply:
    """The gateway relays the provider's refusal of the key."""
    return lambda _sent: error(status, code)


def in_order(*replies: Reply) -> Reply:
    """Each call takes the next reply; the last one repeats."""
    queue: list[Reply] = list(replies)

    def reply(sent: dict[str, Any]) -> httpx.Response:
        return (queue.pop(0) if len(queue) > 1 else queue[0])(sent)

    return reply


@dataclass(slots=True)
class _Gateway:
    """A fake gateway: one reply script per model, every model call kept in call order."""

    replies: Mapping[str, Reply | SlowReply]
    seen: list[str] = field(default_factory=list)

    def calls(self, model: str | None = None) -> int:
        """How many model calls reached the gateway (for ``model``, or in all)."""
        return len(self.seen) if model is None else self.seen.count(model)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one model call from its model's script."""
        sent: dict[str, Any] = json.loads(request.content)
        self.seen.append(sent["model"])
        reply: httpx.Response | Awaitable[httpx.Response] = self.replies[sent["model"]](sent)
        return await reply if inspect.isawaitable(reply) else reply


def _case(candidate_expression: str, case_id: str) -> str:
    """``candidate_expression`` linked to one Case by the Benchmark's own builders."""
    return link_candidate(
        candidate_expression,
        candidate(f"question of {case_id}", case_id=case_id, web_search=False),
    )


async def _run_cases(
    gateway: _Gateway, candidate: str, case_ids: Sequence[str]
) -> tuple[list[str | None], ResolutionError | None]:
    """One run that answers each Case in order through the real Candidate adapter.

    Returns each Case's failure code (None for an answer) and the run-level error raised as the
    run closed (None when the run was not stopped), scoped the way the executor scopes a run.
    """
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=next(iter(gateway.replies)),
            models=tuple(ModelSpec(id=model) for model in gateway.replies),
        ),
        client=client,
    )
    codes: list[str | None] = []
    run_error: ResolutionError | None = None
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        install_branch_runtime(world.node)
        with request_scope(_RUN):
            try:
                with key_refusal_as_url4_error(), stop.refused_key_scope():
                    for case_id in case_ids:
                        try:
                            await url4_run(_case(candidate, case_id), io=world.node)
                            codes.append(None)
                        except Url4Error as exc:
                            codes.append(exc.code)
            except ResolutionError as exc:
                run_error = exc
    finally:
        await world.aclose()
        await client.aclose()
    return codes, run_error


def _cases(count: int) -> list[str]:
    """``count`` distinct Case ids."""
    return [f"case-{n}" for n in range(1, count + 1)]


# --- a solo Candidate ------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "names"),
    [
        (401, "auth_required", "rejected the key"),
        (402, "insufficient_credits", "out of credits"),
        # WHY (review of #2002, P2): the status is the authority. A plugin, string-detail or
        # fallback answer can carry a generic code, and it must stop the run just the same.
        (401, "provider_error", "rejected the key"),
        (402, "provider_error", "out of credits"),
        (402, "aigateway_http_402", "out of credits"),
    ],
)
async def test_the_first_rejected_or_unfunded_key_stops_the_run(
    status: int, code: str, names: str
) -> None:
    gateway = _Gateway({"solo": refused(status, code)})

    codes, run_error = await _run_cases(gateway, _SOLO, _cases(4))

    # WHY 1: neither refusal can succeed on the next Case, so nothing more is sent.
    assert gateway.calls() == 1
    # The refused Case keeps its own failure; the three after it are refused by the Engine.
    assert codes == [code, stop.STOP_CODE, stop.STOP_CODE, stop.STOP_CODE]
    assert run_error is not None
    assert (run_error.code, run_error.permanent) == (stop.STOP_CODE, True)
    assert names in str(run_error) and "solo" in str(run_error)


@pytest.mark.asyncio
async def test_the_same_403_on_five_cases_in_a_row_stops_the_run() -> None:
    gateway = _Gateway({"solo": refused(403, _REFUSED_403)})

    codes, run_error = await _run_cases(gateway, _SOLO, _cases(100))

    # WHY 5 and not 100: this is the 2026-11-19 incident, cut from one call per Case to five.
    assert gateway.calls() == stop.REFUSALS_BEFORE_STOP == 5
    assert codes == [_REFUSED_403] * 5 + [stop.STOP_CODE] * 95
    assert run_error is not None and run_error.code == stop.STOP_CODE
    assert "HTTP 403 on 5 Cases in a row" in str(run_error)


@pytest.mark.asyncio
async def test_the_stop_message_never_carries_the_gateways_text() -> None:
    """The message is engine-vouched (``ENGINE_ERROR_CODES``), so upstream text must not ride it."""
    gateway = _Gateway(
        {
            "solo": lambda _sent: httpx.Response(
                403, json={"detail": {"code": "sk-leaked-code", "message": "sk-leaked-message"}}
            )
        }
    )

    _codes, run_error = await _run_cases(gateway, _SOLO, _cases(5))

    assert run_error is not None
    assert "sk-leaked" not in str(run_error)


@pytest.mark.asyncio
async def test_a_live_answer_between_refusals_starts_the_count_over() -> None:
    no = refused(403, _REFUSED_403)
    gateway = _Gateway({"solo": in_order(no, no, no, no, live(), no, no, no, no)})

    codes, run_error = await _run_cases(gateway, _SOLO, _cases(9))

    # WHY: a 403 can belong to one input (a prompt the provider's moderation flagged). A key
    # that still answers is not refused, so four flagged Cases on each side stop nothing.
    assert run_error is None
    assert codes == [_REFUSED_403] * 4 + [None] + [_REFUSED_403] * 4


@pytest.mark.asyncio
async def test_a_cached_answer_neither_counts_nor_restarts_the_count() -> None:
    no = refused(403, _REFUSED_403)
    gateway = _Gateway({"solo": in_order(no, no, no, no, cached(), no)})

    codes, run_error = await _run_cases(gateway, _SOLO, _cases(8))

    # WHY: a stored reply never asked the provider, so it says nothing about the key. Had it
    # restarted the count, a half-cached rerun of a disabled key would never stop.
    assert codes[:6] == [_REFUSED_403] * 4 + [None, _REFUSED_403]
    assert run_error is not None and run_error.code == stop.STOP_CODE
    assert gateway.calls() == 6


@pytest.mark.asyncio
async def test_a_different_refusal_starts_the_count_over() -> None:
    a, b = refused(403, _REFUSED_403), refused(403, "another_code")
    gateway = _Gateway({"solo": in_order(a, a, a, a, b, b, b, b, refused(400, "bad_request"))})

    codes, run_error = await _run_cases(gateway, _SOLO, _cases(9))

    assert run_error is None
    assert stop.STOP_CODE not in codes


@pytest.mark.asyncio
async def test_attempts_of_one_case_count_as_one_case() -> None:
    gateway = _Gateway({"solo": refused(403, _REFUSED_403)})

    # WHY: a Benchmark that asks each Case several times sends the same flagged input each
    # time. Eight refused Attempts of ONE Case are one Case's failure, not a refused key.
    _codes, run_error = await _run_cases(gateway, _SOLO, ["case-1"] * 8)

    assert run_error is None
    assert gateway.calls() == 8


# --- Candidates that survive a refused call ---------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "code"), [(402, "insufficient_credits"), (403, _REFUSED_403)])
async def test_a_quorum_fusion_survives_its_refused_optional_member(status: int, code: str) -> None:
    gateway = _Gateway(
        {
            "good-a": live("A"),
            "good-b": live("A"),
            "bad": refused(status, code),
            "synth": live("A"),
        }
    )

    codes, run_error = await _run_cases(gateway, _QUORUM, _cases(6))

    # WHY (review of #2002): quorum 2 lets the panel drop its optional member, so every Case
    # is still answered. A refused member call that no Case failed on must never stop the run.
    assert run_error is None
    assert codes == [None] * 6
    assert gateway.calls("bad") == 6


@pytest.mark.asyncio
async def test_a_refused_synthesiser_stops_the_quorum_fusion() -> None:
    gateway = _Gateway(
        {
            "good-a": live("A"),
            "good-b": live("A"),
            "bad": live("A"),
            "synth": refused(402, "insufficient_credits"),
        }
    )

    codes, run_error = await _run_cases(gateway, _QUORUM, _cases(3))

    # WHY: the members answered, but the Case failed with the synthesiser's own refusal, which
    # fails every next Case the same way.
    assert codes == ["insufficient_credits", stop.STOP_CODE, stop.STOP_CODE]
    assert run_error is not None and run_error.code == stop.STOP_CODE
    assert gateway.calls("synth") == 1


@pytest.mark.asyncio
async def test_a_quorum_whose_every_member_is_refused_stops_the_run() -> None:
    no_credits = refused(402, "insufficient_credits")
    gateway = _Gateway(
        {"good-a": no_credits, "good-b": no_credits, "bad": no_credits, "synth": live("A")}
    )

    codes, run_error = await _run_cases(gateway, _QUORUM, _cases(3))

    # WHY: the Case may fail with the panel's own code rather than the refusal's, but no call
    # of it answered, so the refusal is the cause. The synthesiser is never reached.
    assert codes[0] is not None and codes[1:] == [stop.STOP_CODE] * 2
    assert run_error is not None and run_error.code == stop.STOP_CODE
    assert gateway.calls("synth") == 0


@pytest.mark.asyncio
async def test_a_fallback_gate_that_answers_keeps_the_run_going() -> None:
    gateway = _Gateway(
        {"prov/primary": refused(402, "insufficient_credits"), "prov/backup": live("A")}
    )

    codes, run_error = await _run_cases(gateway, _FALLBACK, _cases(6))

    # WHY: ``sf.escalate_if(sf.unanswered())`` exists to answer when the first tier cannot.
    assert run_error is None
    assert codes == [None] * 6
    assert gateway.calls("prov/backup") == 6


@pytest.mark.asyncio
async def test_a_row_policy_that_keeps_its_other_rows_keeps_the_run_going() -> None:
    def rows(sent: dict[str, Any]) -> httpx.Response:
        # Row a is refused for credits; row b answers.
        prompt: str = json.dumps(sent["messages"])
        return (refused(402, "insufficient_credits") if "row-a" in prompt else live("B"))(sent)

    gateway = _Gateway({"rows": rows})

    codes, run_error = await _run_cases(gateway, _ROWS, _cases(6))

    assert run_error is None
    assert codes == [None] * 6


@pytest.mark.asyncio
async def test_a_row_policy_that_collected_only_refusals_stops_the_run() -> None:
    gateway = _Gateway({"rows": refused(402, "insufficient_credits")})

    codes, run_error = await _run_cases(gateway, _ROWS, _cases(3))

    # WHY: the Case "answered" with two collected refusals and no answering call, so the
    # refused key is still the cause, and every next Case would be the same.
    assert codes[1:] == [stop.STOP_CODE] * 2
    assert run_error is not None and run_error.code == stop.STOP_CODE
    assert gateway.calls() == 2


# --- the bound: the Benchmark protocol admits one Case at a time -----------------------------


@pytest.mark.asyncio
async def test_the_benchmark_protocol_bounds_the_stop_to_five_cases() -> None:
    """The real Benchmark protocol, 8 Cases, every call refused 403 after a delay.

    WHY (review of #2002, P1): the stop is checked when a Case starts and settled when it ends,
    so it bounds a run's refused calls only because the protocol starts Case N+1 after Case N
    ended. The delay holds each call open: were Cases admitted in parallel, all 8 would be
    sent before the first refusal came back, and this test is where that change shows up.
    """

    async def slow_refusal(sent: dict[str, Any]) -> httpx.Response:
        await asyncio.sleep(0.01)
        return error(403, _REFUSED_403)

    gateway = _Gateway({"solo": slow_refusal})
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model="solo", models=(ModelSpec(id="solo"),)), client=client
    )
    run_error: ResolutionError | None = None
    try:
        install_candidate_invocation(world.node)
        install_cases(
            world.node,
            "/example/cases",
            lambda: json.dumps([{"id": case_id} for case_id in _cases(8)]),
        )

        @world.node.endpoint("/example/aggregate")
        def aggregate(request: Request) -> str:
            return request.context

        protocol = build_evaluation_protocol(
            cases_route="/example/cases",
            case_evaluation=candidate("$item.id", case_id="$item.id", web_search=False),
            selected_case_count=8,
            available_case_count=8,
            aggregate_route="/example/aggregate",
        )
        with request_scope(_RUN):
            try:
                with key_refusal_as_url4_error(), stop.refused_key_scope():
                    await url4_run(link_candidate(_SOLO, protocol), io=world.node)
            except ResolutionError as exc:
                run_error = exc
    finally:
        await world.aclose()
        await client.aclose()

    assert run_error is not None and run_error.code == stop.STOP_CODE
    assert gateway.calls() == stop.REFUSALS_BEFORE_STOP


# --- outside the Candidate, and the run's lifetime --------------------------------------------


@pytest.mark.asyncio
async def test_a_call_outside_a_candidate_case_is_never_counted() -> None:
    """A Benchmark's judge calls go through the connector with no Case watch open."""
    refusals: list[httpx.Response | BaseException] = [error(403, _REFUSED_403) for _ in range(8)]
    gateway = ScriptedGateway(refusals)

    with stop.refused_key_scope():
        for _ in range(8):
            _tally, _answer, failure = await run_call(gateway, _RUN, web_search=False)
            assert failure is not None and failure.code == _REFUSED_403

    assert len(gateway.calls(CHAT)) == 8


@pytest.mark.asyncio
async def test_one_runs_refusals_never_reach_the_next_run() -> None:
    """The state is bound per run: local mode serves every run from one process and one world."""
    first, _ = await _run_cases(_Gateway({"solo": refused(403, _REFUSED_403)}), _SOLO, _cases(4))
    second, run_error = await _run_cases(
        _Gateway({"solo": refused(403, _REFUSED_403)}), _SOLO, _cases(4)
    )

    assert run_error is None
    assert first == second == [_REFUSED_403] * 4


@pytest.mark.asyncio
async def test_a_cancelled_run_stays_cancelled_after_a_stop() -> None:
    """A stop or deadline is its own terminal reason; the stop error must not replace it."""
    with pytest.raises(asyncio.CancelledError), stop.refused_key_scope():
        with pytest.raises(ResolutionError), stop.watch_case_refusals("case-1"):
            stop.note_refusal(MODEL, status=402, code="insufficient_credits")
            raise ResolutionError("refused", code="insufficient_credits", permanent=True)
        raise asyncio.CancelledError


def test_outside_a_run_nothing_is_counted_or_refused() -> None:
    """The sync surface and direct runs bind no run holder; the rule is then a no-op."""
    with stop.watch_case_refusals("case-1"):
        stop.note_refusal(MODEL, status=402, code="insufficient_credits")
        assert stop.note_answer(MODEL, "an answer") == "an answer"


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
        # Stands in for the Candidate adapter: its Case watch is open, and its one model call is
        # refused for credits, as the connector reports it.
        with key_refusal_as_url4_error(), stop.watch_case_refusals(None):
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


# --- the Gateway codes the Engine lifts (gateway code provenance) ----------------------------


@pytest.mark.asyncio
async def test_two_undeclared_403_codes_extend_one_streak() -> None:
    """WHY (gateway code provenance, OME-2010): the Engine lifts only a code the Gateway declares.

    Any other 403 code reads ``aigateway_http_403``, so a proxy that refuses the key with a
    different code each time still builds one streak, and the run stops after five Cases. Before
    the closed rule the two codes alternated and restarted the count on every Case.
    """
    a, b = refused(403, "proxy_forbidden"), refused(403, "edge_denied")
    gateway = _Gateway({"solo": in_order(a, b, a, b, a)})

    codes, run_error = await _run_cases(gateway, _SOLO, _cases(8))

    assert gateway.calls() == stop.REFUSALS_BEFORE_STOP == 5
    assert codes == ["aigateway_http_403"] * 5 + [stop.STOP_CODE] * 3
    assert run_error is not None and run_error.code == stop.STOP_CODE
