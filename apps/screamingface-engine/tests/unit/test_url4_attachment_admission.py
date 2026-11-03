"""A url4 run's files are refused for a model that can't read them, before any call (OME-1809).

FEATURE (OME-1809, spec #1450 C9; owner decisions A + i, 2026-11-03): picture and PDF admission
(OME-1548, OME-1803) guard the Benchmark Cases route only. A url4 run's own files (#1587 manifest,
#1588 content parts) reach every model call the run makes, so a text-only member used to be called
and billed, and the run then failed on the provider's error (OME-1551 e2e F4).

Now the run's first model call admits the whole run once: it reads the gateway's model list, works
out every model the run's url4 calls (members, reducer, synthesizer) and refuses each one that can't
take the files with ONE permanent ``intent_error`` naming it by its gateway id (e2e N3), before any
request is sent. Each later call carrying files re-checks its own model against the same read, so
a model only known at run time (a computed processor) is refused before ITS send.
INVARIANT: a run with no attachments never reads the model list.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

import httpx
import pytest
from test_aigateway_connector import _MockAigateway

from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.picture_admission import (
    PART_MODALITIES,
    run_expression_scope,
)
from screamingface_engine.benchmarks.url4_attachment_admission import (
    attachment_needs,
    part_type_for,
    run_model_routes,
)
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import Attachment, RelExpr, text
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run

pytestmark = pytest.mark.asyncio

# WHY a colon in the blind model's id: its route spells it `~` (OME-873) while the gateway's list
# spells it `:`; the refusal must name the gateway's spelling — the MODEL, never its provider (N3).
_VISION = "openai/gpt-4o-mini"
_VISION_ROUTE = "/" + _VISION
_BLIND = "ollama/llama3:8b"
_BLIND_ROUTE_ID = "ollama/llama3~8b"
_BLIND_ROUTE = "/" + _BLIND_ROUTE_ID
_SEER = "anthropic/claude-sonnet-4-5"
_SEER_ROUTE = "/" + _SEER
_EYES_ONLY = "google/gemini-flash-image"
_EYES_ONLY_ROUTE = "/" + _EYES_ONLY

_PNG = b"\x89PNG\r\n\x1a\n"
_PDF = b"%PDF-1.4"
_CHAT = "/v1/chat/completions"
_MODEL_LIST = "/v1/models"


def _file(body: bytes, media_type: str) -> Attachment:
    return Attachment(
        digest="sha256:" + hashlib.sha256(body).hexdigest(), media_type=media_type, body=body
    )


def _png() -> Attachment:
    return _file(_PNG, "image/png")


def _pdf() -> Attachment:
    return _file(_PDF, "application/pdf")


class _SightGateway(_MockAigateway):
    """The connector's mock gateway, whose ``/v1/models`` lists each model's input types."""

    def __init__(
        self, catalogue: Mapping[str, Sequence[str]], *, model_list_status: int = 200
    ) -> None:
        route_ids = tuple(model.replace(":", "~") for model in catalogue)
        super().__init__(
            route_ids, responses={m: f"{m} answers" for m in catalogue}, web_search=False
        )
        self.catalogue = catalogue
        self.model_list_status = model_list_status

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != _MODEL_LIST:
            return super()._handle(request)
        self.requests.append(request)
        if self.model_list_status != 200:
            return httpx.Response(self.model_list_status, json={"detail": "unavailable"})
        rows = [{"id": m, "input_modalities": list(v)} for m, v in self.catalogue.items()]
        return httpx.Response(200, json={"object": "list", "data": rows})

    def chat_posts(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == _CHAT]

    def chat_models(self) -> list[str]:
        return [json.loads(r.content)["model"] for r in self.chat_posts()]

    def model_list_reads(self) -> int:
        return sum(1 for r in self.requests if r.url.path == _MODEL_LIST)


async def _run(
    gw: _SightGateway,
    url4: str,
    *attachments: Attachment,
    default_model: str,
    processor: str | None = None,
) -> str:
    """Run ``url4`` as a Runner run does: its url4 bound, the node's world, the files attached."""
    cfg = AigatewayConfig(models=gw.models, default_model=default_model)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        try:
            with run_expression_scope(url4):
                return await url4_run(
                    url4, world.node, processor=processor, attachments=attachments
                )
        finally:
            await world.aclose()


async def _refusal(gw: _SightGateway, url4: str, *files: Attachment, **kw: str) -> ResolutionError:
    with pytest.raises(BaseException) as caught:
        await _run(gw, url4, *files, **kw)
    error = _the_resolution_error(caught.value)
    assert error is not None, repr(caught.value)
    return error


def _the_resolution_error(exc: BaseException) -> ResolutionError | None:
    """The refusal, also when url4 surfaces it inside an exception group."""
    if isinstance(exc, ResolutionError):
        return exc
    for inner in getattr(exc, "exceptions", ()):
        found = _the_resolution_error(inner)
        if found is not None:
            return found
    cause = exc.__cause__
    return None if cause is None else _the_resolution_error(cause)


def _protocol(route: str) -> RelExpr:
    """A stand-in Benchmark protocol: one call that runs the linked Candidate."""
    return RelExpr(path=route, context="$candidate", intent=text("Run."))


def _ensemble(*routes: str, prompt: str = "Describe the picture.") -> str:
    members = ", ".join(f"{route}('{prompt}')!'Answer.'" for route in routes)
    return f"({members})!'Merge the answers.'"


# --- the ticket's acceptance criteria -------------------------------------------------------


async def test_a_text_only_member_over_an_image_is_refused_before_any_chat_call() -> None:
    # The F4 repro: gpt-4o-mini + a text-only member over a picture. Before, gpt-4o-mini answered
    # and was billed, then the text-only call failed upstream.
    gw = _SightGateway({_VISION: ["text", "image"], _BLIND: ["text"]})

    error = await _refusal(
        gw, _ensemble(_VISION_ROUTE, _BLIND_ROUTE), _png(), default_model=_VISION
    )

    assert error.code == "intent_error"
    assert error.permanent is True
    assert _BLIND in str(error)
    assert "image" in str(error)
    # Only the blind model is named; the capable member and reducer are not.
    assert _VISION not in str(error)
    assert gw.chat_posts() == []


async def test_a_pdf_to_an_image_only_reducer_is_refused() -> None:
    # The members read PDFs; the node's default processor (the fan-out reducer) sees pictures only.
    gw = _SightGateway(
        {
            _SEER: ["text", "image", "pdf"],
            _VISION: ["text", "image", "pdf"],
            _EYES_ONLY: ["text", "image"],
        }
    )

    error = await _refusal(
        gw, _ensemble(_SEER_ROUTE, _VISION_ROUTE), _pdf(), default_model=_EYES_ONLY
    )

    assert error.code == "intent_error"
    assert error.permanent is True
    assert _EYES_ONLY in str(error)
    assert "pdf" in str(error)
    assert gw.chat_posts() == []


async def test_one_refusal_names_every_blind_model_and_what_each_lacks() -> None:
    gw = _SightGateway(
        {_SEER: ["text", "image", "pdf"], _BLIND: ["text"], _EYES_ONLY: ["text", "image"]}
    )

    error = await _refusal(
        gw,
        _ensemble(_SEER_ROUTE, _BLIND_ROUTE, _EYES_ONLY_ROUTE),
        _png(),
        _pdf(),
        default_model=_SEER,
    )

    message = str(error)
    assert f"{_BLIND} (image, pdf)" in message
    assert f"{_EYES_ONLY} (pdf)" in message
    assert _SEER not in message
    assert gw.chat_posts() == []


async def test_a_capable_lineup_runs_unchanged() -> None:
    gw = _SightGateway({_VISION: ["text", "image"], _SEER: ["text", "image", "pdf"]})

    result = await _run(gw, _ensemble(_VISION_ROUTE, _SEER_ROUTE), _png(), default_model=_SEER)

    assert result == f"{_SEER} answers"
    assert sorted(gw.chat_models()) == sorted([_VISION, _SEER, _SEER])
    for post in gw.chat_posts():
        first = json.loads(post.content)["messages"][-1]["content"][0]
        assert first["type"] == "image_url"
    assert gw.model_list_reads() == 1


async def test_an_unreadable_model_list_fails_closed_with_no_call() -> None:
    # Owner decision 2026-10-28: unknown never means capable; nothing was spent, so it is retryable.
    gw = _SightGateway(
        {_VISION: ["text", "image"], _SEER: ["text", "image"]}, model_list_status=503
    )

    error = await _refusal(gw, _ensemble(_VISION_ROUTE, _SEER_ROUTE), _png(), default_model=_SEER)

    assert error.code == "resolution_failed"
    assert error.permanent is False
    assert gw.chat_posts() == []
    assert gw.model_list_reads() == 1


async def test_a_run_without_attachments_never_reads_the_model_list() -> None:
    gw = _SightGateway({_VISION: ["text"], _BLIND: ["text"]})

    await _run(gw, _ensemble(_VISION_ROUTE, _BLIND_ROUTE), default_model=_VISION)

    assert gw.model_list_reads() == 0
    assert sorted(gw.chat_models()) == sorted([_VISION, _BLIND, _VISION])


async def test_concurrent_members_share_one_admission() -> None:
    # Three members start together; they wait on ONE admission, so the list is read once.
    gw = _SightGateway(
        {_VISION: ["text", "image"], _SEER: ["text", "image"], _EYES_ONLY: ["text", "image"]}
    )

    await _run(
        gw, _ensemble(_VISION_ROUTE, _SEER_ROUTE, _EYES_ONLY_ROUTE), _png(), default_model=_SEER
    )

    assert gw.model_list_reads() == 1
    assert len(gw.chat_posts()) == 4


async def test_concurrent_members_all_wait_on_a_refusal_and_none_sends() -> None:
    gw = _SightGateway({_VISION: ["text", "image"], _SEER: ["text", "image"], _BLIND: ["text"]})

    await _refusal(
        gw, _ensemble(_VISION_ROUTE, _SEER_ROUTE, _BLIND_ROUTE), _png(), default_model=_SEER
    )

    assert gw.model_list_reads() == 1
    assert gw.chat_posts() == []


async def test_a_computed_processor_is_refused_by_the_per_call_guard_before_its_send() -> None:
    # A Form-3 processor (§27.3) names the reducer only at run time, so the up-front set cannot
    # hold it. The members are capable and may already have answered; the blind reducer's call is
    # refused before it is sent.
    gw = _SightGateway({_VISION: ["text", "image"], _SEER: ["text", "image"], _BLIND: ["text"]})

    error = await _refusal(
        gw,
        _ensemble(_VISION_ROUTE, _SEER_ROUTE),
        _png(),
        default_model=_SEER,
        processor=f"('{_BLIND_ROUTE}')!''",
    )

    assert error.code == "intent_error"
    assert error.permanent is True
    assert _BLIND in str(error)
    assert _BLIND not in gw.chat_models()
    assert gw.model_list_reads() == 1


async def test_a_linked_candidates_members_are_admitted_up_front() -> None:
    # A Benchmark run carries its Candidate as inert text (`definition.link_candidate`); its
    # members are still known before the run starts, so a blind one is refused before any call.
    gw = _SightGateway({_VISION: ["text", "image"], _BLIND: ["text"]})
    url4 = link_candidate(_ensemble(_VISION_ROUTE, _BLIND_ROUTE), _protocol(_VISION_ROUTE))

    error = await _refusal(gw, url4, _png(), default_model=_VISION)

    assert error.code == "intent_error"
    assert _BLIND in str(error)
    assert gw.chat_posts() == []


# --- what the files need --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("media_type", "part_type"),
    [
        ("image/png", "image_url"),
        ("IMAGE/JPEG; q=1", "image_url"),
        ("application/pdf", "file"),
        ("text/csv", "file"),
    ],
)
async def test_a_file_becomes_the_part_type_the_connector_sends(
    media_type: str, part_type: str
) -> None:
    assert part_type_for(media_type) == part_type


async def test_the_files_need_the_modalities_of_their_parts() -> None:
    assert attachment_needs([_png(), _pdf()]) == frozenset({"image", "pdf"})
    assert attachment_needs([_png(), _png()]) == frozenset({"image"})
    assert attachment_needs([]) == frozenset()


async def test_the_part_table_matches_the_benchmark_routes() -> None:
    # AIDEV-NOTE: identical to #1645's (OME-1803) table; the two unify when it merges.
    assert dict(PART_MODALITIES) == {"image_url": "image", "file": "pdf"}


# --- which models a run calls (the DAG walk) -------------------------------------------------

_ROUTES = frozenset({"/a", "/b", "/c", "/d"})


async def test_a_fan_out_reduce_adds_the_runs_processor() -> None:
    url4 = "(/a('x')!'p', /b('y')!'q')!'merge'"
    assert run_model_routes(url4, _ROUTES, default_route="/d") == {"/a", "/b", "/d"}


async def test_a_group_that_only_picks_calls_no_processor() -> None:
    url4 = "(a: /a('x')!'p', t: 'note')!'$a'"
    assert run_model_routes(url4, _ROUTES, default_route="/d") == {"/a"}


async def test_a_literal_processor_parameter_adds_its_route() -> None:
    url4 = "/v1?processor=/c&q=(/a('x')!'p', /b('y')!'q')!'merge'"
    assert {"/a", "/b", "/c"} <= run_model_routes(url4, _ROUTES, default_route="/d")


async def test_a_lazy_fragment_and_a_map_body_are_walked() -> None:
    url4 = "(x: (/a('x')!'p', /b('y')!'q')!'merge', r: ('[\"1\"]')*(/c($item)!'x')!'go')!'$x $r'"
    assert run_model_routes(url4, _ROUTES, default_route="/d") == {"/a", "/b", "/c", "/d"}


async def test_a_candidate_carried_as_text_is_walked() -> None:
    url4 = link_candidate("(/a('x')!'p', /b('y')!'q')!'merge'", _protocol("/c"))
    assert run_model_routes(url4, _ROUTES, default_route="/d") == {"/a", "/b", "/c", "/d"}


async def test_a_templated_route_is_left_to_the_per_call_guard() -> None:
    # `/m/$name` resolves only at run time; the walk names nothing it cannot read.
    url4 = "(name: 'a', /m/$name)!'go'"
    assert run_model_routes(url4, _ROUTES | {"/m/a"}, default_route="/d") == frozenset()


async def test_routes_that_are_not_models_are_dropped() -> None:
    url4 = "(/a('x')!'p', /ensemble/combine/v1('y')!'q')!'merge'"
    assert run_model_routes(url4, _ROUTES, default_route=None) == {"/a"}


@pytest.mark.parametrize("url4", ["", "(((", "not url4 at all"])
async def test_an_unreadable_url4_names_no_model(url4: str) -> None:
    assert run_model_routes(url4, _ROUTES, default_route="/d") == frozenset()


async def test_the_walk_is_bounded_on_a_self_similar_fragment() -> None:
    # Deeper than the fragment cap: the walk stops (incomplete, never wrong) instead of running on.
    nested = "(/a('x')!'p')!'go'"
    for _ in range(200):
        nested = f"(x: {nested})!'$x'"
    assert run_model_routes(nested, _ROUTES, default_route="/d") <= {"/a", "/d"}
