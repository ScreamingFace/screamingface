"""A Judge retry after an unparseable reply gets a fresh reply, not the cached garbled one.

FEATURE (OME-1533): healthbench and gdpval-text nest each Judge call inside a verdict route. A
reply the verdict cannot parse fails the route with ``judge_reply_invalid``, and the verdict
source's ``;retry=`` asks the Judge again. That retry sends the same bytes, and the AI
Gateway's global request cache has already stored the garbled reply (it stores any successful
reply), so before this fix every retry got the same garbled reply back and the Case failed.
draco nests its Judge the same way but records a garbled reply as invalid Evidence instead of
retrying it; its test pins that the fix leaves it alone.

STORY: as someone running one of these Benchmarks with the hosted cache on, a garbled judge reply
costs one extra judge call, not the whole Case.

Every test here talks to ``_CachingGateway``, a fake AI Gateway that keeps the real gateway's
cache rule: a participating request reads and stores; a request carrying
``{"cache": {"use-cache": false}}`` neither reads nor stores. It does not prove the real
gateway's key material; it proves what the Engine SENDS and what a cache with that rule
would serve back.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from benchmark_support import install_benchmarks

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.draco.definition import DRACO
from screamingface_engine.benchmarks.draco.definition import JUDGE_MODEL as DRACO_JUDGE
from screamingface_engine.benchmarks.failure_classes import JUDGE_REPLY_INVALID_CODE
from screamingface_engine.benchmarks.gdpval import runtime as gdpval_runtime
from screamingface_engine.benchmarks.gdpval.revision_inputs import JUDGE_MODEL as GDPVAL_JUDGE
from screamingface_engine.benchmarks.gdpval.revision_inputs import JUDGE_PARAMS as GDPVAL_PARAMS
from screamingface_engine.benchmarks.gdpval.revision_inputs import (
    JUDGE_RETRIES as GDPVAL_RETRIES,
)
from screamingface_engine.benchmarks.healthbench import runtime as healthbench_runtime
from screamingface_engine.benchmarks.healthbench.revision_inputs import (
    JUDGE_MODEL as HEALTHBENCH_JUDGE,
)
from screamingface_engine.benchmarks.healthbench.revision_inputs import (
    JUDGE_PARAMS as HEALTHBENCH_PARAMS,
)
from screamingface_engine.benchmarks.healthbench.revision_inputs import (
    JUDGE_RETRIES as HEALTHBENCH_RETRIES,
)
from screamingface_engine.benchmarks.shared_grading.judge_evidence import rubric_verdict_call
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    capture_grading_requests,
    register_grading_request,
)
from screamingface_engine.operation_calls import capture_request_accounting
from screamingface_engine.request_scope import RequestScope
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import (
    AigatewayConfig,
    AigatewayWorld,
    build_aigateway_world,
)
from screamingface_engine.world.fresh_judge_retry import scope_for_this_send
from url4 import Node, RelExpr, Text, build, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.dag import GuardNode, GuardRetry, current_guard_retry, run
from url4.io.static import StaticIOLayer
from url4.streaming.protocol import CachePolicy

pytestmark = pytest.mark.asyncio

_OPT_OUT: dict[str, bool] = {"use-cache": False}
_GARBLED = "I think the answer is fine"  # prose: no JSON, no verdict field
_RUBRIC_VERDICT = json.dumps({"explanation": "ok", "criteria_met": True})
_CRITERION_VERDICT = json.dumps({"explanation": "ok", "criterion_status": "MET"})
_CANDIDATE_MODEL = "openrouter/anthropic/claude-opus-4.8"
_CANDIDATE_ANSWER = "Four."
_VERDICT_ROUTE = "/verdict"


@dataclass
class _CachingGateway:
    """A fake AI Gateway with the real cache rule and a scripted judge.

    ``judge_script`` is consumed one entry per judge request the gateway actually ANSWERS (a
    cache hit consumes nothing): a ``str`` is a 200 reply with that content, an ``int`` is that
    HTTP error status. Once the script runs out the judge answers ``judge_default``.
    """

    judge_model: str
    judge_script: list[str | int]
    judge_default: str
    bodies: list[dict[str, Any]] = field(default_factory=list)
    _stored: dict[str, str] = field(default_factory=dict)

    def judge_bodies(self) -> list[dict[str, Any]]:
        """Every judge request body the Engine sent, in order."""
        return [body for body in self.bodies if body["model"] == self.judge_model]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Serve one chat completion: from the cache when it may, else from the script."""
        body: dict[str, Any] = json.loads(request.content)
        self.bodies.append(body)
        participates: bool = body.get("cache", {}).get("use-cache", True) is not False
        key: str = json.dumps({k: v for k, v in body.items() if k != "cache"}, sort_keys=True)
        if participates and key in self._stored:
            return _completion(self._stored[key])
        if body["model"] != self.judge_model:
            reply: str | int = _CANDIDATE_ANSWER
        else:
            reply = self.judge_script.pop(0) if self.judge_script else self.judge_default
        if isinstance(reply, int):
            # A gateway error is never stored, exactly like the real cache.
            return httpx.Response(reply, json={"detail": {"code": "upstream_error"}})
        if participates:
            self._stored[key] = reply
        return _completion(reply)


def _completion(content: str) -> httpx.Response:
    """One successful chat-completions reply carrying ``content``."""
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


async def _world(gateway: _CachingGateway, client: httpx.AsyncClient) -> AigatewayWorld:
    """A real Engine world whose model routes reach the fake gateway through the real connector."""
    return await build_aigateway_world(
        AigatewayConfig(
            default_model=_CANDIDATE_MODEL,
            models=(ModelSpec(id=_CANDIDATE_MODEL), ModelSpec(id=gateway.judge_model)),
        ),
        client=client,
    )


def _without_cache(body: dict[str, Any]) -> dict[str, Any]:
    """A request body minus its cache control: what the gateway's cache key is built from."""
    return {k: v for k, v in body.items() if k != "cache"}


# --- healthbench and gdpval-text: the shared rubric verdict wiring -------------------------


@dataclass(frozen=True)
class _RubricBenchmark:
    """One rubric Benchmark's real verdict route and pinned judge, as its variant wires them."""

    name: str
    verdict_factory: Callable[[str], Callable[..., str]]
    judge_model: str
    judge_params: tuple[tuple[str, str], ...]
    retries: int


_RUBRIC_BENCHMARKS = (
    _RubricBenchmark(
        "healthbench",
        healthbench_runtime._rubric_verdict,  # pyright: ignore[reportPrivateUsage]
        HEALTHBENCH_JUDGE,
        HEALTHBENCH_PARAMS,
        HEALTHBENCH_RETRIES,
    ),
    _RubricBenchmark(
        "gdpval-text",
        gdpval_runtime._rubric_verdict,  # pyright: ignore[reportPrivateUsage]
        GDPVAL_JUDGE,
        GDPVAL_PARAMS,
        GDPVAL_RETRIES,
    ),
)


@pytest.fixture(params=_RUBRIC_BENCHMARKS, ids=lambda benchmark: benchmark.name)
def rubric_benchmark(request: pytest.FixtureRequest) -> Iterator[_RubricBenchmark]:
    """Each rubric Benchmark whose verdict route nests its judge call."""
    yield request.param


async def _grade_one_rubric_item(
    benchmark: _RubricBenchmark, gateway: _CachingGateway
) -> dict[str, Any]:
    """Grade one rubric item exactly as the variant nests it: judge inside the verdict, ;retry=.

    The verdict route is the Benchmark's real one; the judge call goes through the real
    connector to the fake gateway. Only the grader prompt is a stand-in (the word "prompt").
    """
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway), base_url="http://aigateway.test"
    ) as client:
        world = await _world(gateway, client)
        world.node.endpoint(_VERDICT_ROUTE)(benchmark.verdict_factory(benchmark.name))
        judge = RelExpr(
            path=f"/{benchmark.judge_model}",
            context="prompt",
            intent=Text(""),
            params=benchmark.judge_params,
        )
        expression = expr(
            rubric_verdict_call(
                judge,
                case_id="1",
                rubric_id="1",
                route=_VERDICT_ROUTE,
                retry=benchmark.retries,
            ),
            intent=Text("$verdict"),
        )
        try:
            with capture_request_accounting():
                with capture_grading_requests():
                    # What the rubric-tasks route does for a real item: tell grading accounting
                    # which Evidence item owns this exact Judge request.
                    register_grading_request(
                        GradingEvidenceOwner(
                            benchmark_id=benchmark.name, case_id=1, check_id="1", sequence=1
                        ),
                        path=f"/{benchmark.judge_model}",
                        params=dict(benchmark.judge_params),
                        context="prompt",
                        intent="",
                    )
                    result = await world.node.evaluate(render(expression))
        finally:
            await world.aclose()
    return json.loads(result.text)


async def test_a_retry_after_an_unparseable_judge_reply_skips_the_cache_and_the_item_grades(
    rubric_benchmark: _RubricBenchmark,
) -> None:
    # THE bug: the gateway stored the garbled first reply, and the retry used to send the same
    # bytes under the run's own policy, so the cache served the garbled reply on every retry and
    # the item failed. The retry must opt out so the gateway asks the judge again.
    gateway = _CachingGateway(rubric_benchmark.judge_model, [_GARBLED], _RUBRIC_VERDICT)

    record = await _grade_one_rubric_item(rubric_benchmark, gateway)

    assert record["valid"] is True
    assert record["criteria_met"] is True
    first, retry = gateway.judge_bodies()
    assert "cache" not in first
    assert retry["cache"] == _OPT_OUT
    # Only the cache control differs: the retry asks the SAME question, so it keeps the same
    # cache key and request identity (what accounting is keyed by).
    assert _without_cache(retry) == first


async def test_the_fresh_retry_is_billed_to_the_same_evidence_item(
    rubric_benchmark: _RubricBenchmark,
) -> None:
    # WHY: the opt-out lives in the body's cache control, which the accounting request key does
    # not read — so the garbled first send AND the fresh retry both book to rubric item 1 of
    # Case 1 (1 + 1 input tokens), not to nobody.
    gateway = _CachingGateway(rubric_benchmark.judge_model, [_GARBLED], _RUBRIC_VERDICT)

    record = await _grade_one_rubric_item(rubric_benchmark, gateway)

    assert record["accounting"]["usage"]["input_tokens"] == 2
    assert record["accounting"]["usage"]["output_tokens"] == 2


async def test_the_first_judge_ask_participates_in_the_cache(
    rubric_benchmark: _RubricBenchmark,
) -> None:
    # WHY: a first ask is the common case and the one cache-backed replays are recorded from;
    # it must keep the run's own policy (for a default run: no cache field at all).
    gateway = _CachingGateway(rubric_benchmark.judge_model, [], _RUBRIC_VERDICT)

    record = await _grade_one_rubric_item(rubric_benchmark, gateway)

    assert record["valid"] is True
    (only,) = gateway.judge_bodies()
    assert "cache" not in only


async def test_a_retry_after_a_gateway_5xx_still_participates_in_the_cache(
    rubric_benchmark: _RubricBenchmark,
) -> None:
    # WHY: a 5xx stored nothing, so the cache cannot echo it — an opt-out would only stop the
    # good reply that follows from being stored, which is what cache-backed replays read.
    gateway = _CachingGateway(rubric_benchmark.judge_model, [502], _RUBRIC_VERDICT)

    record = await _grade_one_rubric_item(rubric_benchmark, gateway)

    assert record["valid"] is True
    first, retry = gateway.judge_bodies()
    assert "cache" not in first
    assert "cache" not in retry


async def test_every_retry_after_unparseable_replies_skips_the_cache(
    rubric_benchmark: _RubricBenchmark,
) -> None:
    # WHY: the fresh reply of a retry can itself be garbled; the NEXT retry must also be fresh,
    # or it would read whatever a participating copy of the request left in the cache.
    gateway = _CachingGateway(rubric_benchmark.judge_model, [_GARBLED, _GARBLED], _RUBRIC_VERDICT)

    record = await _grade_one_rubric_item(rubric_benchmark, gateway)

    assert record["valid"] is True
    assert [body.get("cache") for body in gateway.judge_bodies()] == [None, _OPT_OUT, _OPT_OUT]


# --- draco: a whole Case through the real Engine, with accounting -------------------------


def _draco_assets(root: Path) -> None:
    """One-criterion DRACO assets for all 100 Cases (the Benchmark preflights every Case)."""
    (root / "criteria").mkdir(parents=True)
    (root / "rubrics").mkdir()
    cases: list[dict[str, object]] = [
        {"id": case_id, "input": f"Question {case_id}", "domain": "Arithmetic"}
        for case_id in range(1, 101)
    ]
    (root / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    criteria = [{"id": "answer", "requirement": "Answers.", "criterion_type": "positive"}]
    rubric = {"sections": [{"id": "correctness", "criteria": [{"id": "answer", "weight": 3}]}]}
    for case_id in range(1, 101):
        (root / "criteria" / f"{case_id}.json").write_text(json.dumps(criteria), encoding="utf-8")
        (root / "rubrics" / f"{case_id}.json").write_text(json.dumps(rubric), encoding="utf-8")


def _linked_draco_case() -> str:
    """One DRACO Case with a single-model Candidate, linked the way a run submits it."""
    candidate: Node = RelExpr(
        path=f"/{_CANDIDATE_MODEL}", context="$input", intent=text("Answer exactly.")
    )
    benchmark = DRACO.resource(1)["url4"]
    assert isinstance(benchmark, str)
    return render(
        expr(
            src(text(render(candidate)), name="candidate", weight=0.0),
            build(benchmark),
            intent=text(""),
        )
    )


async def test_draco_records_a_garbled_pass_as_invalid_evidence_and_never_opts_out(
    tmp_path: Path,
) -> None:
    # WHY draco is pinned, not changed: its verdict route RETURNS an unparseable reply as invalid
    # Evidence instead of raising, so its ;retry= fires only on 429/5xx/transport failures and a
    # garbled pass is never re-asked — there is no cache echo to fix. This pins that the fix
    # leaves draco's sends alone: one send per pass, none opted out, the Case still graded.
    _draco_assets(tmp_path / "draco")
    gateway = _CachingGateway(DRACO_JUDGE, [_GARBLED], _CRITERION_VERDICT)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway), base_url="http://aigateway.test"
    ) as client:
        world = await _world(gateway, client)
        install_benchmarks(world.node, tmp_path, benchmarks=(DRACO,))
        try:
            result = await world.node.evaluate(_linked_draco_case())
        finally:
            await world.aclose()

    (case,) = json.loads(result.text)["cases"]
    assert case["status"] == "scored"
    assert case["grade"]["metrics"]["verdicts_invalid"] == 1
    judge_bodies = gateway.judge_bodies()
    assert len(judge_bodies) == case["grade"]["metrics"]["verdicts_expected"]
    assert all("cache" not in body for body in judge_bodies)


# --- the helper on its own: what an opted-out send keeps ----------------------------------


class _ScopePerSend:
    """A guarded stand-in leaf that records the scope each send would run under.

    It simulates the connector reading the retry and the scope at call time (the same two
    lines); the failure codes it raises are the ones a verdict route (``judge_reply_invalid``)
    or the connector (``upstream_error``) would raise. It does not exercise a real route.
    """

    deps: dict = {}

    def __init__(self, scope: RequestScope, *failure_codes: str) -> None:
        self._scope = scope
        self._failure_codes: list[str] = list(failure_codes)
        self.scopes: list[RequestScope] = []

    async def resolve(self, inputs: object, ctx: object) -> str:
        """Record this send's scope, then fail with the next scripted code or answer."""
        retry: GuardRetry | None = current_guard_retry()
        self.scopes.append(
            scope_for_this_send(self._scope, None if retry is None else retry.failure_code)
        )
        if self._failure_codes:
            raise ResolutionError("send failed", code=self._failure_codes.pop(0))
        return "answer"


_CALLER_SCOPE = RequestScope(
    identity_headers={"X-Example-Identity": "caller"},
    answer_seed=7,
    cache=CachePolicy(participate=True, max_age=60),
    origin="sync",
    deadline=123.0,
)


async def test_an_opted_out_retry_changes_only_the_cache_policy() -> None:
    # WHY: the retry must still bill and log as the same caller with the same seed; only the
    # cache control may differ, or the fix would leak into identity or attribution.
    leaf = _ScopePerSend(_CALLER_SCOPE, JUDGE_REPLY_INVALID_CODE)

    assert await run(GuardNode(leaf, retries=1), StaticIOLayer()) == "answer"

    first, retry = leaf.scopes
    assert first is _CALLER_SCOPE
    assert retry.cache == CachePolicy(participate=False)
    assert replace(retry, cache=_CALLER_SCOPE.cache) == _CALLER_SCOPE


async def test_a_retry_after_any_other_failure_keeps_the_callers_scope() -> None:
    # WHY: only an unusable-but-successful Judge reply is stored and echoed by the cache; a
    # retry after an upstream failure must keep storing its good reply.
    leaf = _ScopePerSend(_CALLER_SCOPE, "upstream_error", "timeout")

    assert await run(GuardNode(leaf, retries=2), StaticIOLayer()) == "answer"

    assert all(scope is _CALLER_SCOPE for scope in leaf.scopes)


async def test_an_unguarded_call_keeps_the_callers_scope() -> None:
    assert scope_for_this_send(_CALLER_SCOPE, None) is _CALLER_SCOPE


# --- the fix moves no Benchmark ------------------------------------------------------------

# The revisions on main before OME-1533. The fix lives in how a retry is SENT, never in what a
# Benchmark asks, so no hashed input moved and every published score stays addressable.
_REVISIONS_BEFORE_THE_FIX: dict[str, str] = {
    "healthbench-worst30": "39cfd96b068f7230",
    "healthbench-professional": "d8fb037307f35415",
    "gdpval-text": "cacfc3e6b83765f6",
    "draco": "62718f04ea1a980f",
    "draco-3pass": "2634cec91fd0f19a",
}


async def test_the_fresh_retry_moves_no_benchmark_revision() -> None:
    revisions: dict[str, str] = {
        benchmark.id: benchmark.revision
        for benchmark in BUILTIN_BENCHMARKS
        if benchmark.id in _REVISIONS_BEFORE_THE_FIX
    }

    assert revisions == _REVISIONS_BEFORE_THE_FIX
