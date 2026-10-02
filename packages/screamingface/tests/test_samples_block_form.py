"""Self-consistency in block form runs like the named form (OME-1289, BK#12).

STORY: a researcher writes ``Fusion(sf.samples(model, 5), synthesizer=sf.Reduce("plurality", ...))``
and evaluates it through a real ``sf.Client``. The Candidate must be byte-identical to the
``sf.Vote`` one, so the same requests go out, five answers are counted and the report is the same.

WHY a guard: ``sf.Reduce`` is a ``Reducer`` and compiles to the same bytes as its named class (unit
4), and ``sf.samples`` sets the seeds (unit 6). So this passes at once. The handler below follows
``test_fixed_seed_sitting_warning.py`` (it serves the ``seed`` parameter row) and is copied, not
imported, so that module stays free to change.
"""

from __future__ import annotations

import copy
from typing import Any

import httpx
from _model_parameter_fixtures import DETAILS as _DETAILS
from _model_parameter_fixtures import SUMMARY as _SUMMARY
from _reducer_fixtures import evidence_wire, operators_response
from _vote_run_fixtures import ScriptedTransport, case_wire, operation_wire, spec_of
from url4 import RelExpr, build, expr, render, src, text

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate
from screamingface.url4 import _calls, _candidate_expression

_BENCHMARK_URL4 = render(
    expr(
        src(
            RelExpr(path="/candidate", context="question", intent=text("$candidate")),
            name="answer",
            weight=0.0,
        ),
        intent=text("$answer"),
    )
)
_BENCHMARK = {
    "schema": "screamingface.benchmark.v1",
    "id": "fixture",
    "title": "Fixture",
    "description": "Fixture Benchmark.",
    "revision": "fixture-revision",
    "case_count": 1,
    "url4": _BENCHMARK_URL4,
}
_MODEL = "provider/opus"
_ROUTES = (_MODEL,)
_SEED_ROW = {
    "request_path": "seed",
    "schema": {"type": "integer"},
    "provider": {
        "support": "supported",
        "source": "openrouter:models",
        "stale": False,
        "deprecated": False,
    },
    "gateway": {
        "status": "enabled",
        "projection": "direct",
        "cache_behavior": "keyed",
        "applicable_auth_modes": ["api_key"],
    },
}
_OUTPUTS = ["The answer is 4"] * 3 + ["The answer is 5"] * 2
_MEMBERS = [f"member_{index}" for index in range(1, 6)]


def _details(model: str) -> dict[str, object]:
    value: dict[str, Any] = copy.deepcopy(_DETAILS)
    provider, upstream = model.split("/", 1)
    value["model"] = {"id": model, "gateway_provider": provider, "upstream_id": upstream}
    value["parameters"]["seed"] = _SEED_ROW
    return value


def _summary(model: str) -> dict[str, object]:
    return {
        **_SUMMARY,
        "id": model,
        "owned_by": model.split("/", 1)[0],
        "parameter_contract_url": f"/v1/model-parameters?model={model}",
    }


def _handler(paths: list[str]) -> Any:
    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        response = httpx.Response(404)
        if request.url.path == "/v1/benchmarks/fixture":
            response = httpx.Response(200, json=_BENCHMARK)
        elif request.url.path == "/v1/operators":
            response = operators_response()
        elif request.url.path == "/v1/models":
            data = [_summary(model) for model in _ROUTES]
            response = httpx.Response(200, json={"object": "list", "data": data})
        elif request.url.path == "/v1/model-parameters":
            response = httpx.Response(200, json=_details(request.url.params["model"]))
        return response

    return handle


def _case_for(candidate: Candidate) -> list[dict[str, Any]]:
    ops = spec_of(candidate.url4)
    operators = [ops[stage]["op"] for stage in ("extract", "normalize", "reduce", "select")]  # type: ignore[index]
    values = ["4", "4", "4", "5", "5"]
    evidence = evidence_wire(
        5,
        operators=operators,
        members=[
            {
                "member_id": member,
                "raw": value,
                "value": value,
                "status": "answered",
                "reason": None,
                "signals": {},
                "weight": 1.0,
                "score": 1.0,
            }
            for member, value in zip(_MEMBERS, values, strict=True)
        ],
        tally=[
            {"value": "4", "score": 3.0, "holders": ["member_1", "member_2", "member_3"]},
            {"value": "5", "score": 2.0, "holders": ["member_4", "member_5"]},
        ],
        chosen=["member_1"],
        agreement=0.6,
        tie=False,
        result={"member_id": "member_1", "value": "4", "status": "answered", "reason": None},
        dropped=0,
    )
    operations = [
        operation_wire(f"op_model_{index}", text_) for index, text_ in enumerate(_OUTPUTS, start=1)
    ]
    operations.append(operation_wire("op_synthesis_1", "The answer is 4", combine=evidence))
    return [case_wire("The answer is 4", operations)]


class _CountingTransport(ScriptedTransport):
    def __init__(self) -> None:
        super().__init__("fixture", "fixture-revision", _case_for)
        self.runs = 0

    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        self.runs += 1
        return super().run(candidate, on_event)


def _evaluate(recipe: sf.Recipe) -> tuple[sf.Report, _CountingTransport, list[str]]:
    paths: list[str] = []
    transport = _CountingTransport()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_handler(paths)),
        run_transport=transport,
    ) as client:
        report = client.evaluate(recipe, benchmark="fixture", progress=False)
    return report, transport, paths


def _block() -> sf.Fusion:
    return sf.Fusion(
        sf.samples(_MODEL, 5),
        synthesizer=sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric")),
    )


def _named() -> sf.Fusion:
    return sf.Fusion(
        sf.samples(_MODEL, 5), synthesizer=sf.Vote(extract="last_number", normalize="numeric")
    )


def _assert_five_seeded_requests(url4: str) -> None:
    candidate, _ = _candidate_expression(build(url4))
    calls = _calls(candidate)
    models = [calls[f"model_{index}"] for index in range(1, 6)]
    assert [call.model for call in models] == [_MODEL] * 5
    assert [dict(call.params)["seed"] for call in models] == ["0", "1", "2", "3", "4"]
    # Everything but the seed is equal, so only the seed tells the five calls apart.
    assert {(call.prompt, call.dependencies) for call in models} == {
        (models[0].prompt, models[0].dependencies)
    }
    assert {tuple((k, v) for k, v in call.params if k != "seed") for call in models} == {
        tuple((k, v) for k, v in models[0].params if k != "seed")
    }


def _assert_vote_spec(url4: str) -> None:
    spec = spec_of(url4)
    assert spec["reducer"] == "vote"
    assert spec["reduce"]["op"].startswith("mode@")  # type: ignore[index]
    assert spec["select"]["op"].startswith("first_holder@")  # type: ignore[index]
    assert spec["weights"] is None


def _assert_five_answers_and_a_computed_one(report: sf.Report) -> None:
    answers = report.candidates[0].cases.by_id(1).answers()
    assert len(answers) == 6
    members, computed = answers[:5], answers[5]
    assert [answer.member_id for answer in members] == _MEMBERS
    assert [answer.value for answer in members] == ["4", "4", "4", "5", "5"]
    assert [answer.text for answer in members] == _OUTPUTS
    assert (computed.member_id, computed.value) == ("member_1", "4")


def test_samples_with_reduce_plurality_runs_self_consistency() -> None:
    block_report, block_transport, block_paths = _evaluate(_block())
    named_report, named_transport, named_paths = _evaluate(_named())

    assert block_transport.candidate is not None
    assert named_transport.candidate is not None
    # The same Candidate bytes: the same five requests and the same combine call.
    url4 = block_transport.candidate.url4
    assert url4 == named_transport.candidate.url4
    _assert_five_seeded_requests(url4)
    _assert_vote_spec(url4)
    assert block_report.to_json() == named_report.to_json()
    _assert_five_answers_and_a_computed_one(block_report)
    assert block_transport.runs == named_transport.runs == 1
    assert block_paths.count("/v1/model-parameters") == 1
    assert named_paths.count("/v1/model-parameters") == 1

    # The named class wins on recovery, so the block form prints as sf.Vote (BK#12, F3).
    python = sf.Url4(url4).to_python()
    assert "sf.Vote(extract='last_number@" in python
    assert "sf.Reduce(" not in python
