"""A url4 run's attachments are refused for blind models before any model call (OME-1809).

FEATURE: image and PDF inputs (epic ``OME-1529``). Spec
``docs/spec/2026-11-09-blind-model-admission.md``; plan ``docs/plan/2026-11-09-…``.
STORY: as an ensemble author whose url4 carries a picture or a PDF, a lineup with a model that
cannot take it fails at once with ONE ``intent_error`` naming every such model — before any
chat call is paid for — instead of one gateway 422 per member mid-run.
INVARIANT: one ``/v1/models`` read per run, shared by every call; an unreadable list fails the
run retryably (never "no blind models"); a model the gateway does not list is blind (OME-1537).
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import httpx
import pytest

from screamingface_engine.benchmarks.picture_admission import (
    IMAGE_MODALITY,
    PDF_MODALITY,
    attachment_modality,
    run_expression_scope,
)
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import Attachment
from url4.core.errors import ResolutionError
from url4.dag.attachments import bind_run_files

pytestmark = pytest.mark.asyncio

_PNG = b"\x89PNG\r\n\x1a\n"
_PDF = b"%PDF-1.4"
SEEING = "acme/vision-1"
PDF_SEEING = "acme/omni-1"
BLIND = "meta-llama/llama-3.3-70b-instruct"
BLIND_2 = "acme/text-2"
UNLISTED = "acme/ghost-1"
_LISTED: dict[str, list[str]] = {
    SEEING: ["text", "image"],
    PDF_SEEING: ["text", "image", "pdf"],
    BLIND: ["text"],
    BLIND_2: ["text"],
}


def _png() -> Attachment:
    return Attachment(
        digest="sha256:" + hashlib.sha256(_PNG).hexdigest(), media_type="image/png", body=_PNG
    )


def _pdf() -> Attachment:
    return Attachment(
        digest="sha256:" + hashlib.sha256(_PDF).hexdigest(),
        media_type="application/pdf",
        body=_PDF,
    )


class _Gateway:
    """``/v1/models`` with input types, plus chat; counts both."""

    def __init__(self, *, models_status: int = 200) -> None:
        self.models_status = models_status
        self.model_reads = 0
        self.chats: list[dict] = []

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            self.model_reads += 1
            # WHY a yield: concurrent members must find the read in flight, not finished.
            await asyncio.sleep(0.01)
            if self.models_status != 200:
                return httpx.Response(self.models_status, json={"detail": "down"})
            data = [{"id": m, "input_modalities": mods} for m, mods in _LISTED.items()]
            return httpx.Response(200, json={"object": "list", "data": data})
        assert request.url.path == "/v1/chat/completions"
        self.chats.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "42"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


_ALL = (SEEING, PDF_SEEING, BLIND, BLIND_2, UNLISTED)


async def _run(
    url4: str,
    attachments: tuple[Attachment, ...],
    gw: _Gateway,
    *,
    default_model: str = SEEING,
    scoped: bool = True,
) -> str:
    cfg = AigatewayConfig(
        models=tuple(ModelSpec(id=m, web_search=False) for m in _ALL), default_model=default_model
    )
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        try:
            with bind_run_files(attachments):
                if not scoped:
                    return str(await world.node.evaluate(url4))
                with run_expression_scope(url4):
                    return str(await world.node.evaluate(url4))
        finally:
            await world.aclose()


def _members(*models: str) -> str:
    calls = ", ".join(f"m{i}:/{m}('Look.')!'Describe.'" for i, m in enumerate(models))
    return f"({calls})!'Pick one.'"


# --- T1: media type -> input type -------------------------------------------------------------


async def test_media_types_map_to_the_gateways_input_types() -> None:
    assert attachment_modality("image/png") == IMAGE_MODALITY
    assert attachment_modality("image/webp") == IMAGE_MODALITY
    assert attachment_modality("application/pdf") == PDF_MODALITY
    assert attachment_modality("text/plain") is None


async def test_a_pdf_run_refuses_a_model_that_lists_image_but_not_pdf() -> None:
    gw = _Gateway()
    with pytest.raises(ResolutionError) as caught:
        await _run(_members(SEEING, PDF_SEEING), (_pdf(),), gw, default_model=PDF_SEEING)

    assert caught.value.code == "intent_error"
    assert SEEING in str(caught.value) and PDF_SEEING not in str(caught.value)
    assert gw.chats == []


# --- T2/T3: the run check, through the connector ----------------------------------------------


async def test_an_image_run_with_a_text_only_member_is_refused_before_any_chat_call() -> None:
    gw = _Gateway()
    with pytest.raises(ResolutionError) as caught:
        await _run(_members(SEEING, BLIND), (_png(),), gw)

    assert caught.value.code == "intent_error"
    assert caught.value.permanent is True
    assert BLIND in str(caught.value)
    assert gw.chats == []


async def test_the_refusal_names_every_blind_model_once_sorted() -> None:
    gw = _Gateway()
    with pytest.raises(ResolutionError) as caught:
        await _run(_members(BLIND_2, BLIND, SEEING, BLIND), (_png(),), gw)

    message = str(caught.value)
    assert f"{BLIND_2}, {BLIND}" in message
    assert message.count(BLIND) == 1


async def test_a_model_the_gateway_does_not_list_counts_as_blind() -> None:
    gw = _Gateway()
    with pytest.raises(ResolutionError) as caught:
        await _run(_members(SEEING, UNLISTED), (_png(),), gw)

    assert UNLISTED in str(caught.value)
    assert gw.chats == []


# --- T4: once per run ---------------------------------------------------------------------------


async def test_parallel_members_share_one_model_list_read() -> None:
    gw = _Gateway()
    with pytest.raises(ResolutionError):
        await _run(_members(BLIND, SEEING, BLIND_2), (_png(),), gw)

    assert gw.model_reads == 1


async def test_a_capable_lineup_reads_the_list_once_and_runs() -> None:
    gw = _Gateway()
    await _run(_members(SEEING, PDF_SEEING, SEEING), (_png(),), gw)

    assert gw.model_reads == 1
    # three members and the reduce on the (seeing) default processor
    assert len(gw.chats) == 4


# --- T5: what is NOT checked ------------------------------------------------------------------


async def test_a_text_run_never_reads_the_model_list() -> None:
    gw = _Gateway()
    await _run(_members(BLIND, BLIND_2), (), gw)

    assert gw.model_reads == 0
    assert len(gw.chats) == 3


async def test_a_capable_lineup_sends_the_same_bodies_as_an_unchecked_run() -> None:
    checked, unchecked = _Gateway(), _Gateway()
    await _run(_members(SEEING, PDF_SEEING), (_png(),), checked)
    await _run(_members(SEEING, PDF_SEEING), (_png(),), unchecked, scoped=False)

    assert unchecked.model_reads == 0
    key = lambda body: json.dumps(body, sort_keys=True)  # noqa: E731
    assert sorted(map(key, checked.chats)) == sorted(map(key, unchecked.chats))


# --- T6: route coverage -----------------------------------------------------------------------


async def test_the_synthesizer_route_is_checked() -> None:
    # The Fusion shape the SDK compiles: instrumental members, a synthesizer over them.
    gw = _Gateway()
    url4 = (
        f"(m0:0.0:/{SEEING}('Look.')!'Describe.', "
        f"s:0.0:/{BLIND}({{outputs: {{m0: '$m0'}}}})!'Synthesize.')!'$s'"
    )
    with pytest.raises(ResolutionError) as caught:
        await _run(url4, (_png(),), gw)

    assert BLIND in str(caught.value)
    assert gw.chats == []


async def test_the_default_processor_is_checked_when_the_run_fans_out() -> None:
    gw = _Gateway()
    with pytest.raises(ResolutionError) as caught:
        await _run(_members(SEEING), (_png(),), gw, default_model=BLIND)

    assert BLIND in str(caught.value)
    assert gw.chats == []


async def test_the_default_processor_is_not_checked_when_nothing_reduces() -> None:
    # An all-instrumental group (the Fusion extraction idiom) merges locally: the default
    # processor never receives the file, so a blind default does not refuse the run.
    gw = _Gateway()
    url4 = f"(m0:0.0:/{SEEING}('Look.')!'Describe.')!'$m0'"
    assert await _run(url4, (_png(),), gw, default_model=BLIND) == "42"

    assert len(gw.chats) == 1


# --- T7: unreadable list fails closed ---------------------------------------------------------


async def test_an_unreadable_model_list_fails_the_run_retryably_before_any_call() -> None:
    gw = _Gateway(models_status=503)
    with pytest.raises(ResolutionError) as caught:
        await _run(_members(SEEING, PDF_SEEING), (_png(),), gw)

    assert caught.value.code == "resolution_failed"
    assert caught.value.permanent is False
    assert gw.model_reads == 1
    assert gw.chats == []


# --- T8: the Benchmark path is unchanged ------------------------------------------------------


async def test_a_benchmark_run_checks_only_its_candidate_never_the_grader() -> None:
    # A Benchmark run's url4 also names the protocol's grader; a text-only judge never gets a
    # file (spec D6), so only the linked Candidate's routes count.
    from test_picture_admission import _AGGREGATE_ROUTE, _BLIND_ROUTE, _CASES_ROUTE, _single

    from screamingface_engine.benchmarks.definition import link_candidate
    from screamingface_engine.benchmarks.picture_admission import run_model_routes
    from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
    from url4 import RelExpr, text

    protocol = build_evaluation_protocol(
        cases_route=_CASES_ROUTE,
        case_evaluation=RelExpr(path=_BLIND_ROUTE, context="$item.input", intent=text("Grade.")),
        selected_case_count=1,
        available_case_count=1,
        aggregate_route=_AGGREGATE_ROUTE,
    )
    run = link_candidate(_single(SEEING), protocol)

    routes = run_model_routes(
        run, frozenset({"/" + SEEING, _BLIND_ROUTE}), default_route=_BLIND_ROUTE
    )
    assert routes == frozenset({"/" + SEEING})
