"""A PDF Benchmark refuses a Candidate model that can't take PDFs, before any paid call.

FEATURE (OME-1803, spec OME-1760 §3.4): the exam desk of OME-1548 now checks PDFs too. If any Case
in the file carries a ``file`` part, every model in the Candidate must list ``pdf`` in the
gateway's ``/v1/models`` ``input_modalities``; one that does not fails the whole run by name with
the permanent ``intent_error``, and no member is paid. The key is the published modality list,
never the model's name. The gateway's 422 stays the backstop when admission misses.
INVARIANT (C9): picture admission is unchanged; `test_picture_admission.py` pins it untouched.
"""

from __future__ import annotations

import json
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
    IMAGE_MODALITY,
    PDF_MODALITY,
    cases_need_modalities,
    models_lacking,
)
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, expr, render, src, struct, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request

# WHY these names: the reader is a model whose list carries `pdf`; the deaf one lists only text,
# and the gateway spells its id with `:` while its route spells `~` (OME-873).
_READER: str = "anthropic/claude-sonnet-4-5"
_DEAF: str = "ollama/llama3:8b"
_DEAF_ROUTE_ID: str = "ollama/llama3~8b"
_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(id=_READER, web_search=False),
    ModelSpec(id=_DEAF_ROUTE_ID, web_search=False),
)
_CATALOGUE: list[dict[str, Any]] = [
    {"id": _READER, "input_modalities": ["text", "image", "pdf"]},
    {"id": _DEAF, "input_modalities": ["text"]},
]
_CHAT: str = "/v1/chat/completions"
_MODEL_LIST: str = "/v1/models"
_CASES_ROUTE: str = "/papers/cases"
_AGGREGATE_ROUTE: str = "/papers/aggregate"

# WHY `JVBERi0=` ("%PDF-"): a data URI the envelope reader accepts; nothing here opens the file.
_PDF: dict[str, Any] = {
    "type": "file",
    "file": {"file_data": "data:application/pdf;base64,JVBERi0=", "filename": "paper.pdf"},
}
_PICTURE: dict[str, Any] = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
}


def _media_case(*parts: dict[str, Any], question: str = "What does the paper conclude?") -> str:
    """A v2 envelope: the given media parts, then the question."""

    return json.dumps(
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [{"role": "user", "content": [*parts, {"type": "text", "text": question}]}],
        }
    )


def _text_case() -> str:
    return json.dumps(
        {"schema": CANDIDATE_INPUT_SCHEMA, "messages": [{"role": "user", "content": "6 x 7?"}]}
    )


def _rows(*inputs: object) -> list[dict[str, object]]:
    return [{"id": f"c{index}", "input": value} for index, value in enumerate(inputs)]


def _single(model: str) -> str:
    return render(RelExpr(path="/" + model, context="$input", intent=text("Answer.")))


def _fusion(members: tuple[str, ...], synthesizer: str) -> str:
    """Members, then a synthesizer over ``{"input", "outputs"}``, as the SDK compiles a Fusion."""

    sources = [
        src(
            RelExpr(path="/" + member, context="$input", intent=text("Answer.")),
            name=f"model_{index}",
            weight=0.0,
        )
        for index, member in enumerate(members, start=1)
    ]
    outputs = {f"member_{index}": f"$model_{index}" for index in range(1, len(members) + 1)}
    context = render(struct({"input": "$input", "outputs": outputs}))
    synthesis = src(
        RelExpr(path="/" + synthesizer, context=context, intent=text("Synthesize.")),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(*sources, synthesis, intent=text("$synthesis_1")))


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

    def count(self, path: str) -> int:
        return sum(1 for request in self.requests if request.url.path == path)


async def _run(
    gateway: _Gateway, recipe: str, rows: list[dict[str, object]]
) -> BaseException | None:
    """Run one Benchmark through `Url4Executor`, the Runner's own path; return how it failed."""

    cfg = AigatewayConfig(models=_MODELS, default_model=_READER)
    transport = httpx.MockTransport(gateway.handle)
    async with httpx.AsyncClient(transport=transport, base_url="http://aigateway.test") as client:
        world = await build_aigateway_world(cfg, client=client)
        install_candidate_invocation(world.node)
        install_cases(world.node, _CASES_ROUTE, lambda: json.dumps(rows))

        @world.node.endpoint(_AGGREGATE_ROUTE)
        def aggregate(request: Request) -> str:
            return request.context

        protocol = build_evaluation_protocol(
            cases_route=_CASES_ROUTE,
            case_evaluation=candidate("$item.input", web_search=False),
            selected_case_count=len(rows),
            available_case_count=len(rows),
            aggregate_route=_AGGREGATE_ROUTE,
        )
        executor = Url4Executor(world.node)
        try:
            with request_scope(RequestScope(origin="run")):
                async for _step in executor.execute(link_candidate(recipe, protocol)):
                    pass
        except ResolutionError as exc:
            return exc
        finally:
            await world.aclose()
    return None


# ── Which input types does a Cases file need? ─────────────────────────────────────────────


def test_a_case_with_a_file_part_needs_pdf() -> None:
    assert cases_need_modalities(_rows(_text_case(), _media_case(_PDF))) == {PDF_MODALITY}


def test_a_picture_case_needs_image_only() -> None:
    assert cases_need_modalities(_rows(_media_case(_PICTURE))) == {IMAGE_MODALITY}


def test_a_file_needing_both_needs_both() -> None:
    rows = _rows(_media_case(_PICTURE), _media_case(_PDF))

    assert cases_need_modalities(rows) == {IMAGE_MODALITY, PDF_MODALITY}


def test_a_text_file_needs_nothing() -> None:
    assert cases_need_modalities(_rows(_text_case(), "plain", None)) == frozenset()


def test_a_pdf_case_the_reader_refuses_is_not_counted() -> None:
    # WHY: a broken envelope fails its own Case at the connector; nothing in it reaches a model.
    broken: str = _media_case(_PDF).replace("application/pdf", "application/msword")

    assert cases_need_modalities(_rows(broken)) == frozenset()


# ── Which models lack it? ─────────────────────────────────────────────────────────────────


def test_a_model_whose_list_lacks_pdf_is_named() -> None:
    modalities = {_READER: ("text", "pdf"), _DEAF: ("text", "image")}

    assert models_lacking({_READER, _DEAF}, modalities, PDF_MODALITY) == (_DEAF,)


def test_a_model_missing_from_the_gateway_list_lacks_pdf() -> None:
    # INVARIANT (OME-1537): a model the gateway knows nothing about takes text only.
    assert models_lacking({_DEAF}, {_READER: ("pdf",)}, PDF_MODALITY) == (_DEAF,)


# ── End to end: one run through the Runner, on a scripted gateway ─────────────────────────


@pytest.mark.asyncio
async def test_a_mixed_fusion_with_a_member_that_cant_read_pdfs_is_refused_before_any_payment() -> (
    None
):
    gateway = _Gateway()

    failure = await _run(
        gateway, _fusion((_READER, _DEAF_ROUTE_ID), _READER), _rows(_media_case(_PDF))
    )

    assert isinstance(failure, ResolutionError)
    assert failure.code == "intent_error"
    assert failure.permanent is True
    assert _DEAF in str(failure)
    assert _READER not in str(failure)
    assert "PDF" in str(failure)
    assert gateway.count(_MODEL_LIST) == 1
    assert gateway.count(_CHAT) == 0


@pytest.mark.asyncio
async def test_a_model_that_sees_pictures_but_not_pdfs_is_refused() -> None:
    # WHY: the check keys on the `pdf` entry itself; image support says nothing about files.
    listing = [
        {"id": _READER, "input_modalities": ["text", "image", "pdf"]},
        {"id": _DEAF, "input_modalities": ["text", "image"]},
    ]
    gateway = _Gateway(httpx.Response(200, json={"data": listing}))

    failure = await _run(gateway, _single(_DEAF_ROUTE_ID), _rows(_media_case(_PDF)))

    assert isinstance(failure, ResolutionError)
    assert failure.code == "intent_error"
    assert _DEAF in str(failure)
    assert gateway.count(_CHAT) == 0


@pytest.mark.asyncio
async def test_a_model_name_is_not_the_key_only_the_published_list_is() -> None:
    # WHY (spec §3.4): the same id is admitted the moment the gateway lists `pdf` for it.
    listing = [{"id": _DEAF, "input_modalities": ["text", "pdf"]}]
    gateway = _Gateway(httpx.Response(200, json={"data": listing}))

    failure = await _run(gateway, _single(_DEAF_ROUTE_ID), _rows(_media_case(_PDF)))

    assert failure is None
    assert gateway.count(_CHAT) == 1


@pytest.mark.asyncio
async def test_a_pdf_lineup_runs_and_reads_the_model_list_once() -> None:
    gateway = _Gateway()

    failure = await _run(
        gateway, _fusion((_READER, _READER), _READER), _rows(_media_case(_PDF), _text_case())
    )

    assert failure is None
    assert gateway.count(_MODEL_LIST) == 1
    assert gateway.count(_CHAT) == 6


@pytest.mark.asyncio
async def test_a_pdf_model_that_cant_see_pictures_is_still_refused_by_the_picture_rule() -> None:
    listing = [{"id": _DEAF, "input_modalities": ["text", "pdf"]}]
    gateway = _Gateway(httpx.Response(200, json={"data": listing}))

    failure = await _run(gateway, _single(_DEAF_ROUTE_ID), _rows(_media_case(_PICTURE, _PDF)))

    assert isinstance(failure, ResolutionError)
    assert failure.code == "intent_error"
    assert "images" in str(failure)
    assert gateway.count(_CHAT) == 0


@pytest.mark.asyncio
async def test_a_model_lacking_both_is_named_for_both() -> None:
    gateway = _Gateway()

    failure = await _run(
        gateway, _single(_DEAF_ROUTE_ID), _rows(_media_case(_PICTURE), _media_case(_PDF))
    )

    assert isinstance(failure, ResolutionError)
    assert "images" in str(failure)
    assert "PDFs" in str(failure)
    assert gateway.count(_MODEL_LIST) == 1
    assert gateway.count(_CHAT) == 0


@pytest.mark.asyncio
async def test_an_unreadable_model_list_fails_a_pdf_run_as_retryable_before_any_chat_call() -> None:
    # WHY: the owner's posture for the shared reader (OME-1548, 2026-10-28) — spend nothing.
    gateway = _Gateway(httpx.ConnectError("refused"))

    failure = await _run(gateway, _single(_READER), _rows(_media_case(_PDF)))

    assert isinstance(failure, ResolutionError)
    assert failure.permanent is False
    assert gateway.count(_CHAT) == 0
