"""``extract="benchmark"`` resolves to the selected benchmark's answer rule before any spend.

FEATURE: ``sf.Vote(extract="benchmark")`` groups answers the way the benchmark grades them
(OME-1289 gap, GP-1). STORY: as a researcher, I vote with the grader's own reading of an answer, and
a benchmark with no rule, or an Engine without its operators, stops me before any money moves.
INVARIANT: the url4 pins the rule's operator ids, so a replay never looks the rule up again.
"""

from __future__ import annotations

import copy
from typing import Any, NoReturn

import httpx
import pytest
from _combine_contract import (
    AIME24_RULE_WIRE,
    AIME25_RULE_WIRE,
    ENGINE_OPERATOR_NAMES,
    GSM8K_RULE_WIRE,
    PRE_INSPECT_OPERATOR_NAMES,
    engine_operators,
    rule,
)
from _vote_run_fixtures import (
    ScriptedTransport,
    benchmark_resource,
    case_wire,
    engine_handler,
    spec_of,
)
from test_client_run import _ForbiddenTransport

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.answer_rule import _BenchmarkAnswerRule
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import Candidate
from screamingface.reducer import Reducer

_MEMBERS = ["provider/a", "provider/b", "provider/c"]
_GSM8K = "inspect-gsm8k"


def _fusion(synthesizer: Reducer) -> sf.Fusion:
    return sf.Fusion(_MEMBERS, synthesizer=synthesizer)


def _bound(benchmark_id: str, wire: dict[str, Any]) -> _BenchmarkAnswerRule:
    return _BenchmarkAnswerRule(benchmark_id, rule(wire))


def _url4(synthesizer: Reducer, benchmark_rule: _BenchmarkAnswerRule | None = None) -> str:
    return compile_candidate(
        _fusion(synthesizer), operators=engine_operators(), benchmark_rule=benchmark_rule
    ).url4


def test_benchmark_extract_compiles_a_different_url4_per_benchmark() -> None:
    vote = sx.Vote(over="benchmark")
    gsm8k = _url4(vote, _bound(_GSM8K, GSM8K_RULE_WIRE))
    aime24 = _url4(vote, _bound("inspect-aime24", AIME24_RULE_WIRE))
    aime25 = _url4(vote, _bound("inspect-aime25", AIME25_RULE_WIRE))

    assert gsm8k != aime24
    gsm8k_spec, aime_spec = spec_of(gsm8k), spec_of(aime24)
    assert (gsm8k_spec["extract"], gsm8k_spec["normalize"]) == (
        {"op": "inspect_number@1", "args": {}},
        {"op": "inspect_numeric@1", "args": {}},
    )
    assert (aime_spec["extract"], aime_spec["normalize"]) == (
        {"op": "inspect_aime@1", "args": {}},
        {"op": "inspect_numeric@1", "args": {}},
    )
    # F10: the url4 depends on the rule's operators, not the benchmark id.
    assert aime24 == aime25
    # Control: a named rule never looks at the benchmark's rule.
    control = sx.Vote(over="last_number")
    assert (
        _url4(control)
        == _url4(control, _bound(_GSM8K, GSM8K_RULE_WIRE))
        == _url4(control, _bound("inspect-aime24", AIME24_RULE_WIRE))
    )
    no_normalizer = _url4(vote, _bound(_GSM8K, {**GSM8K_RULE_WIRE, "normalize": None}))
    assert spec_of(no_normalizer)["normalize"] is None


def _gsm8k_engine(events: list[str], operators: Any = ENGINE_OPERATOR_NAMES) -> httpx.MockTransport:
    resources = {_GSM8K: benchmark_resource(_GSM8K, answer_rule=GSM8K_RULE_WIRE)}
    return httpx.MockTransport(engine_handler(events, resources=resources, operators=operators))


def _one_case(candidate: Candidate) -> list[dict[str, Any]]:
    del candidate
    return [case_wire("42")]


def test_benchmark_extract_resolves_before_spend() -> None:
    synthesizer = sx.Vote(over="benchmark")
    events: list[str] = []
    transport = ScriptedTransport(_GSM8K, "fixture-revision", _one_case, events)

    with sf.Client(
        engine_url="https://engine.example",
        http_transport=_gsm8k_engine(events),
        run_transport=transport,
    ) as client:
        report = client.evaluate(_fusion(synthesizer), benchmark=_GSM8K, progress=False)

    assert transport.candidate is not None
    spec = spec_of(transport.candidate.url4)
    assert (spec["extract"], spec["normalize"]) == (
        {"op": "inspect_number@1", "args": {}},
        {"op": "inspect_numeric@1", "args": {}},
    )
    assert events.index(f"/v1/benchmarks/{_GSM8K}") < events.index("/v1/operators")
    assert events.index("/v1/operators") < events.index("RUN")
    benchmark_paths = [path for path in events if path.startswith("/v1/benchmarks")]
    assert benchmark_paths == [f"/v1/benchmarks/{_GSM8K}"]
    python = sf.Url4(report.candidates[0].url4).to_python()
    assert "sf.Vote(extract='inspect_number@1', normalize='inspect_numeric@1')" in python
    reported = spec_of(report.candidates[0].url4)
    assert all("benchmark" not in str(reported[stage]) for stage in ("extract", "normalize"))


class _AsyncForbiddenTransport:
    called = False

    async def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("a benchmark without an answer rule must fail before execution")

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _check_no_rule_message(message: str) -> None:
    assert "'draco'" in message
    assert "declares no answer rule" in message
    assert "last_number" in message


def _draco_engine() -> httpx.MockTransport:
    return httpx.MockTransport(
        engine_handler([], resources={"draco": benchmark_resource("draco", case_count=1)})
    )


def test_benchmark_without_rule_raises_before_spend() -> None:
    transport = _ForbiddenTransport()

    with (
        sf.Client(
            engine_url="https://engine.example",
            http_transport=_draco_engine(),
            run_transport=transport,
        ) as client,
        pytest.raises(ValueError, match="declares no answer rule") as caught,
    ):
        client.evaluate(_fusion(sx.Vote(over="benchmark")), benchmark="draco", progress=False)

    _check_no_rule_message(str(caught.value))
    assert transport.called is False


@pytest.mark.asyncio
async def test_async_benchmark_without_rule_raises_before_spend() -> None:
    transport = _AsyncForbiddenTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=_draco_engine(),
        run_transport=transport,
    )

    async with client:
        with pytest.raises(ValueError, match="declares no answer rule") as caught:
            await client.evaluate(
                _fusion(sx.Vote(over="benchmark")), benchmark="draco", progress=False
            )

    _check_no_rule_message(str(caught.value))
    assert transport.called is False


def _without(stage: str, name: str) -> dict[str, tuple[str, ...]]:
    names = copy.deepcopy(ENGINE_OPERATOR_NAMES)
    names[stage] = tuple(item for item in names[stage] if item != name)
    return names


@pytest.mark.parametrize(
    ("operators", "stage", "operator"),
    [
        pytest.param(PRE_INSPECT_OPERATOR_NAMES, "extract", "inspect_number@1", id="no-inspect"),
        pytest.param(
            _without("normalize", "inspect_numeric"),
            "normalize",
            "inspect_numeric@1",
            id="no-inspect-numeric",
        ),
    ],
)
def test_engine_without_inspect_operators_raises_capability_error(
    operators: Any, stage: str, operator: str
) -> None:
    transport = _ForbiddenTransport()

    with (
        sf.Client(
            engine_url="https://engine.example",
            http_transport=_gsm8k_engine([], operators),
            run_transport=transport,
        ) as client,
        pytest.raises(sf.EngineCapabilityError) as caught,
    ):
        client.evaluate(_fusion(sx.Vote(over="benchmark")), benchmark=_GSM8K, progress=False)

    error = caught.value
    assert error.code == "engine_capability_missing"
    assert error.permanent is True
    assert error.details == {"benchmark": _GSM8K, "stage": stage, "operator": operator}
    assert operator in str(error)
    assert transport.called is False
