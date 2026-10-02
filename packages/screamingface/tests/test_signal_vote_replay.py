"""A signal-weighted vote replays identically from its url4 (OME-1289, SR#10 SDK half).

FEATURE: ``sf.Vote(weights=sf.signal("cost_usd"))`` compiles to a url4 that holds everything the
Engine needs: the spec and the combine context `sources`.
STORY: as a researcher, I replay a recorded run from its url4 and the SDK asks the Engine for no
catalog and no benchmark again.
"""

from __future__ import annotations

from typing import Any

import httpx
from _combine_contract import GSM8K_RULE_WIRE, engine_operators
from _vote_run_fixtures import ScriptedTransport, benchmark_resource, case_wire, engine_handler
from test_client_run import _engine
from test_signal_vote_contract_fixture import signal_vote_url4

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import Candidate

_GSM8K = "inspect-gsm8k"
_CATALOG = ("/v1/operators", "/v1/benchmarks")


def _vote() -> sf.Fusion:
    return sf.Fusion(
        ["provider/a", "provider/b", "provider/c"],
        synthesizer=sf.Vote(extract="last_line", normalize="text", weights=sf.signal("cost_usd")),
    )


def _one_case(candidate: Candidate) -> list[dict[str, Any]]:
    del candidate
    return [case_wire("42")]


def _replay_handler(paths: list[str]) -> Any:
    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert not request.url.path.startswith(_CATALOG), "a replay asked for the catalog"
        return _engine(request)

    return handle


def test_signal_reduce_replays_identically_from_cache() -> None:
    assert signal_vote_url4() == signal_vote_url4()
    first = ScriptedTransport(_GSM8K, "fixture-revision", _one_case)
    resources = {_GSM8K: benchmark_resource(_GSM8K, answer_rule=GSM8K_RULE_WIRE)}
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine_handler([], resources=resources)),
        run_transport=first,
    ) as client:
        report = client.evaluate(_vote(), benchmark=_GSM8K, progress=False)
    url4 = report.candidates[0].url4
    original = compile_candidate(_vote(), operators=engine_operators()).url4
    assert "sources: {member_1: {model_1: {path: '/provider/a'" in original

    replay = ScriptedTransport(_GSM8K, "fixture-revision", _one_case)
    paths: list[str] = []
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_replay_handler(paths)),
        run_transport=replay,
    ) as client:
        client.evaluate(url4, progress=False)

    assert not [path for path in paths if path.startswith(_CATALOG)]
    assert replay.candidate is not None
    assert replay.candidate.url4 == url4
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    recovered = namespace["candidate"]
    assert recovered.synthesizer.weights == sf.signal("cost_usd")
    assert type(recovered.synthesizer) is sf.Vote
    assert compile_candidate(recovered, operators=engine_operators()).url4 == original
