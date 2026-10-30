"""A picture Benchmark refuses a Candidate model that can't see pictures, before any paid call.

FEATURE (OME-1548): think of the Cases route as the exam desk. Before the first paper goes out, it
looks at the papers: if any of them has a picture, it reads the gateway's model list once and checks
that every model in the Candidate (members, synthesizer, reducer) reads `image`. One blind model
fails the whole run by name, with the permanent `intent_error`, and nothing has been paid for.
INVARIANT: a text Benchmark never reads the model list, so no text run changes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
import pytest

from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    CANDIDATE_INPUT_V2_SCHEMA,
)
from screamingface_engine.benchmarks.definition import candidate, link_candidate
from screamingface_engine.benchmarks.picture_admission import (
    candidate_model_routes,
    cases_need_pictures,
    text_only_models,
)
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec, routes_for
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, expr, render, src, struct, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request

# WHY a colon in the blind model's id: its route spells it `~` (OME-873) while the gateway's list
# spells it `:`, so this proves the check joins the two spellings rather than comparing strings.
_VISION: str = "anthropic/claude-sonnet-4-5"
_BLIND: str = "ollama/llama3:8b"
_BLIND_ROUTE_ID: str = "ollama/llama3~8b"
_BLIND_ROUTE: str = "/" + _BLIND_ROUTE_ID
_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(id=_VISION, web_search=False),
    ModelSpec(id=_BLIND_ROUTE_ID, web_search=False),
)
_CATALOGUE: list[dict[str, Any]] = [
    {"id": _VISION, "input_modalities": ["text", "image", "pdf"]},
    {"id": _BLIND, "input_modalities": ["text"]},
]
_CHAT: str = "/v1/chat/completions"
_MODEL_LIST: str = "/v1/models"
_CASES_ROUTE: str = "/pictures/cases"
_AGGREGATE_ROUTE: str = "/pictures/aggregate"
_EMAIL: str = "researcher@example.org"

# WHY the docstring's example bytes from `candidate_input.py`: a valid PNG data URI the envelope
# reader accepts. Nothing here opens the picture, so a real image would prove nothing more.
_PICTURE: dict[str, Any] = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
}


def _picture_case(question: str = "What is the height of the tallest bar?") -> str:
    """A LAB-Bench FigQA-shaped Case input: the v2 envelope, one picture, then the question."""

    return json.dumps(
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [
                {"role": "user", "content": [_PICTURE, {"type": "text", "text": question}]}
            ],
        }
    )


def _text_case(question: str = "What is 6 times 7?") -> str:
    """A v1 envelope: text messages only, the shape every text Benchmark imports."""

    return json.dumps(
        {"schema": CANDIDATE_INPUT_SCHEMA, "messages": [{"role": "user", "content": question}]}
    )


def _rows(*inputs: object) -> list[dict[str, object]]:
    return [{"id": f"c{index}", "input": value} for index, value in enumerate(inputs)]


def _single(model: str) -> str:
    """A one-model Candidate, as the SDK compiles `sf.Model(model)`."""

    return render(RelExpr(path="/" + model, context="$input", intent=text("Answer.")))


def _fusion(member: str, synthesizer: str) -> str:
    """One member, then a synthesizer over ``{"input", "outputs"}``, as the SDK compiles it."""

    member_source = src(
        RelExpr(path="/" + member, context="$input", intent=text("Answer.")),
        name="model_1",
        weight=0.0,
    )
    context = render(struct({"input": "$input", "outputs": {"member_1": "$model_1"}}))
    synthesis = src(
        RelExpr(path="/" + synthesizer, context=context, intent=text("Synthesize.")),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(member_source, synthesis, intent=text("$synthesis_1")))


def _benchmark_run(recipe: str, *, selected: int, available: int) -> str:
    """The run url4 a Benchmark run executes: the protocol over the Cases, Candidate linked in."""

    protocol = build_evaluation_protocol(
        cases_route=_CASES_ROUTE,
        case_evaluation=candidate("$item.input", web_search=False),
        selected_case_count=selected,
        available_case_count=available,
        aggregate_route=_AGGREGATE_ROUTE,
    )
    return link_candidate(recipe, protocol)


# ── Stage 1: does a Cases file need pictures? ─────────────────────────────────────────────


def test_a_case_with_an_image_part_needs_pictures() -> None:
    assert cases_need_pictures(_rows(_text_case(), _picture_case())) is True


@pytest.mark.parametrize(
    "value",
    [_text_case(), "What is 6 times 7?", 42, None, {"question": "q"}],
    ids=["v1 envelope", "plain prompt", "a number", "null", "an object"],
)
def test_a_case_without_an_image_part_needs_no_pictures(value: object) -> None:
    assert cases_need_pictures(_rows(value)) is False


def test_a_row_with_no_input_needs_no_pictures() -> None:
    # WHY: hand-built Benchmarks may name their Case fields differently; only `input` is the
    # Candidate's view, so a row without one sends no picture.
    assert cases_need_pictures([{"id": "c0", "question": "q"}]) is False


def test_a_picture_case_the_reader_refuses_is_not_counted() -> None:
    # WHY: a broken envelope fails its own Case at the connector (OME-1271 PR 4), never the run;
    # nothing in it reaches a model, so it is no reason to refuse a model.
    broken: str = _picture_case().replace("data:image/png", "data:image/svg+xml")

    assert cases_need_pictures(_rows(broken)) is False


# ── Stage 2: which models does the Candidate name? ────────────────────────────────────────


def test_a_fusion_names_its_member_and_its_synthesizer() -> None:
    run: str = _benchmark_run(_fusion(_VISION, _BLIND_ROUTE_ID), selected=1, available=1)

    assert candidate_model_routes(run, frozenset(routes_for(_MODELS))) == frozenset(
        {"/" + _VISION, _BLIND_ROUTE}
    )


def test_a_nested_fusion_names_the_models_inside_it() -> None:
    # WHY: the SDK hands a Fusion-as-synthesizer over as quoted url4 text (OME-1741); its models
    # still answer the Case, so they still need to see the picture.
    inner: str = _fusion(_BLIND_ROUTE_ID, _BLIND_ROUTE_ID)
    outer: str = render(
        expr(
            src(
                RelExpr(path="/" + _VISION, context="$input", intent=text("Answer.")),
                name="model_1",
                weight=0.0,
            ),
            src(text(inner), name="synthesis_1", weight=0.0),
            intent=text("$synthesis_1"),
        )
    )
    run: str = _benchmark_run(outer, selected=1, available=1)

    assert _BLIND_ROUTE in candidate_model_routes(run, frozenset(routes_for(_MODELS)))


def test_routes_outside_the_candidate_are_not_named() -> None:
    # WHY: a Benchmark's grader is text only (spec D6) and is not the Candidate's model; a grader
    # route that is also a model route must not be checked.
    protocol = build_evaluation_protocol(
        cases_route=_CASES_ROUTE,
        case_evaluation=RelExpr(path=_BLIND_ROUTE, context="$item.input", intent=text("Grade.")),
        selected_case_count=1,
        available_case_count=1,
        aggregate_route=_AGGREGATE_ROUTE,
    )
    run: str = link_candidate(_single(_VISION), protocol)

    assert candidate_model_routes(run, frozenset(routes_for(_MODELS))) == frozenset({"/" + _VISION})


def test_a_run_with_no_linked_candidate_names_no_model() -> None:
    assert (
        candidate_model_routes(_single(_BLIND_ROUTE_ID), frozenset(routes_for(_MODELS)))
        == frozenset()
    )


# ── Stage 3: which of them cannot take images? ────────────────────────────────────────────


def test_a_text_only_model_is_named_by_its_gateway_id() -> None:
    modalities: Mapping[str, Sequence[str]] = {
        _VISION: ("text", "image"),
        _BLIND: ("text",),
    }

    assert text_only_models({_VISION, _BLIND}, modalities) == (_BLIND,)


def test_a_model_missing_from_the_gateway_list_counts_as_text_only() -> None:
    # INVARIANT: the gateway's own rule (OME-1537) — unknown never means vision.
    assert text_only_models({_BLIND}, {_VISION: ("text", "image")}) == (_BLIND,)


def test_a_vision_lineup_names_nobody() -> None:
    assert text_only_models({_VISION}, {_VISION: ("text", "image")}) == ()


# ── End to end: one run through the Runner, on a scripted gateway ─────────────────────────


class _Gateway:
    """A scripted AI Gateway: the model list, and one answer for every chat call."""

    def __init__(self, catalogue: httpx.Response | BaseException | None = None) -> None:
        self._catalogue = catalogue or httpx.Response(200, json={"data": _CATALOGUE})
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == _MODEL_LIST:
            if isinstance(self._catalogue, BaseException):
                raise self._catalogue
            return self._catalogue
        if request.url.path == _CHAT:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": "42"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        raise AssertionError(f"unexpected gateway request {request.method} {request.url.path}")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), base_url="http://aigateway.test"
        )

    def count(self, path: str) -> int:
        return sum(1 for request in self.requests if request.url.path == path)


async def _run(
    gateway: _Gateway,
    recipe: str,
    rows: list[dict[str, object]],
    *,
    selected: int | None = None,
) -> BaseException | None:
    """Run one Benchmark through `Url4Executor`, the Runner's own path; return how it failed."""

    cfg = AigatewayConfig(models=_MODELS, default_model=_VISION)
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        install_candidate_invocation(world.node)
        install_cases(world.node, _CASES_ROUTE, lambda: json.dumps(rows))

        @world.node.endpoint(_AGGREGATE_ROUTE)
        def aggregate(request: Request) -> str:
            return request.context

        run: str = _benchmark_run(
            recipe, selected=selected if selected is not None else len(rows), available=len(rows)
        )
        executor = Url4Executor(world.node)
        scope = RequestScope(origin="run", identity_headers={"X-User-Email": _EMAIL})
        try:
            with request_scope(scope):
                async for _step in executor.execute(run):
                    pass
        except ResolutionError as exc:
            return exc
        finally:
            await world.aclose()
    return None


@pytest.mark.asyncio
async def test_a_blind_member_fails_the_whole_run_by_name_before_any_chat_call() -> None:
    gateway = _Gateway()

    failure = await _run(
        gateway, _fusion(_BLIND_ROUTE_ID, _VISION), _rows(_picture_case(), _picture_case())
    )

    assert isinstance(failure, ResolutionError)
    assert failure.code == "intent_error"
    assert failure.permanent is True
    assert _BLIND in str(failure)
    assert _VISION not in str(failure)
    assert gateway.count(_CHAT) == 0


@pytest.mark.asyncio
async def test_a_blind_synthesizer_fails_the_run_too() -> None:
    gateway = _Gateway()

    failure = await _run(gateway, _fusion(_VISION, _BLIND_ROUTE_ID), _rows(_picture_case()))

    assert isinstance(failure, ResolutionError)
    assert failure.code == "intent_error"
    assert gateway.count(_CHAT) == 0


@pytest.mark.asyncio
async def test_a_mixed_benchmark_is_refused_even_when_the_selected_cases_are_text() -> None:
    # WHY (owner, 2026-10-28): HLE is 14% pictures. A picture anywhere in the file makes it a
    # picture Benchmark, so a smoke run that happens to draw only text Cases gets the same answer.
    gateway = _Gateway()

    failure = await _run(
        gateway, _single(_BLIND_ROUTE_ID), _rows(_text_case(), _picture_case()), selected=1
    )

    assert isinstance(failure, ResolutionError)
    assert failure.code == "intent_error"
    assert gateway.count(_CHAT) == 0


@pytest.mark.asyncio
async def test_a_vision_lineup_runs_and_reads_the_model_list_once() -> None:
    gateway = _Gateway()

    failure = await _run(
        gateway, _fusion(_VISION, _VISION), _rows(_picture_case(), _picture_case())
    )

    assert failure is None
    assert gateway.count(_MODEL_LIST) == 1
    assert gateway.count(_CHAT) == 4


@pytest.mark.asyncio
async def test_the_model_list_is_read_as_the_runs_caller() -> None:
    # INVARIANT (trust): the gateway answers per caller, so the list is read with the run's own
    # verified identity, the way its chat calls are.
    gateway = _Gateway()

    await _run(gateway, _single(_VISION), _rows(_picture_case()))

    (listing,) = [r for r in gateway.requests if r.url.path == _MODEL_LIST]
    assert listing.headers["X-User-Email"] == _EMAIL


@pytest.mark.asyncio
async def test_a_text_benchmark_never_reads_the_model_list() -> None:
    gateway = _Gateway()

    failure = await _run(
        gateway, _single(_BLIND_ROUTE_ID), _rows(_text_case(), "What is 2 plus 2?")
    )

    assert failure is None
    assert gateway.count(_MODEL_LIST) == 0
    assert gateway.count(_CHAT) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "catalogue",
    [
        httpx.Response(503, json={"detail": "down"}),
        httpx.ConnectError("refused"),
        httpx.Response(200, json={"object": "list"}),
    ],
    ids=["gateway error", "unreachable", "no data"],
)
async def test_an_unreadable_model_list_fails_the_run_as_retryable_before_any_chat_call(
    catalogue: httpx.Response | BaseException,
) -> None:
    # WHY retryable (owner, 2026-10-28): the run cannot know whether its models see pictures, so it
    # spends nothing; a later run may find the gateway answering.
    gateway = _Gateway(catalogue)

    failure = await _run(gateway, _single(_VISION), _rows(_picture_case()))

    assert isinstance(failure, ResolutionError)
    assert failure.permanent is False
    assert gateway.count(_CHAT) == 0


@pytest.mark.asyncio
async def test_a_call_outside_a_runner_run_is_not_checked() -> None:
    # WHY: only a Runner run binds its expression, so the local sync eval path (a development
    # shape, never deployed) has no Candidate to read and is not checked; the gateway's own 422
    # stays its guard. Pinned so that widening the check is a decision, not an accident.
    gateway = _Gateway()
    cfg = AigatewayConfig(models=_MODELS, default_model=_VISION)
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        install_candidate_invocation(world.node)
        install_cases(world.node, _CASES_ROUTE, lambda: json.dumps(_rows(_picture_case())))

        @world.node.endpoint(_AGGREGATE_ROUTE)
        def aggregate(request: Request) -> str:
            return request.context

        try:
            with request_scope(RequestScope(origin="sync")):
                await world.node.evaluate(
                    _benchmark_run(_single(_BLIND_ROUTE_ID), selected=1, available=1)
                )
        finally:
            await world.aclose()

    assert gateway.count(_MODEL_LIST) == 0
    assert gateway.count(_CHAT) == 1
