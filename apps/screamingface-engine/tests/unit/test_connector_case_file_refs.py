"""The connector sends Case files by blob reference, against a fake gateway (OME-1970 PR 7).

FEATURE: with ``[aigateway] blob_refs`` on, the Engine uploads each Case file once per run
(``PUT /v1/blobs/sha256/{digest}``) and every chat call carries ``blob:sha256/<hex>`` plus the
run's token in ``X-AIGW-Run-Token``. Off (the default), every request is today's, byte for byte.
On the inline path, a Case too big for the gateway's body cap is refused when the Cases are
served, before any model call (decision 8).

The fake gateway stands in for aigateway's upload route (`routes/blobs.py`) and chat route; it
answers like them (201 with the type read from the leading bytes, 404 when it has no route).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.case_file_refs import run_case_files
from screamingface_engine.world.config import (
    AigatewaySection,
    ModelSpec,
    WorldConfig,
    WorldConfigError,
    parse_config,
    routes_for,
)
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _ModelEndpoint,
)
from screamingface_engine.world.factory import _aigateway_config
from url4.core.errors import ResolutionError
from url4.peer.server import Request

pytestmark = pytest.mark.asyncio

_MODEL = "anthropic/claude-haiku-4-5"
_TOKEN_HEADER = "x-aigw-run-token"
_PNG_BYTES: bytes = b"\x89PNG\r\n\x1a\n" + b"a bar chart, tallest bar 42"
_PNG_URI: str = "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode("ascii")
_PNG_SHA256: str = hashlib.sha256(_PNG_BYTES).hexdigest()


def _picture_case() -> str:
    """One v2 Case, compact like the importer writes it: a question and one PNG."""
    return json.dumps(
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is the height of the tallest bar?"},
                        {"type": "image_url", "image_url": {"url": _PNG_URI}},
                    ],
                }
            ],
        },
        separators=(",", ":"),
    )


class _FakeGateway:
    """aigateway's upload and chat routes, recording every request.

    ``upload_status``: 201 stores the file as the real route does; 404 is a gateway built before
    the route; any other status answers with that status and ``upload_code``.
    """

    def __init__(self, *, upload_status: int = 201, upload_code: str = "") -> None:
        self.upload_status: int = upload_status
        self.upload_code: str = upload_code
        self.uploads: list[httpx.Request] = []
        self.calls: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request the way the matching aigateway route would."""
        if request.url.path.startswith("/v1/blobs/sha256/"):
            return self._upload(request)
        assert request.url.path == "/v1/chat/completions"
        self.calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "42"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 1, "total_tokens": 12},
            },
        )

    def _upload(self, request: httpx.Request) -> httpx.Response:
        """The upload route: store as the real one does, or answer the configured refusal."""
        self.uploads.append(request)
        if self.upload_status == 404:
            return httpx.Response(404, json={"detail": "Not Found"})
        if self.upload_status != 201:
            return httpx.Response(
                self.upload_status,
                json={"detail": {"code": self.upload_code, "message": "refused"}},
            )
        digest: str = request.url.path.rsplit("/", 1)[1]
        # The real route recomputes the SHA-256 and refuses a mismatch.
        assert hashlib.sha256(request.content).hexdigest() == digest
        return httpx.Response(
            201,
            json={
                "ref": f"blob:sha256/{digest}",
                "media_type": "image/png",
                "size_bytes": len(request.content),
            },
        )

    def client(self) -> httpx.AsyncClient:
        """An httpx client whose every request reaches this fake."""
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


def _endpoint(client: httpx.AsyncClient, cfg: AigatewayConfig) -> _ModelEndpoint:
    """The handler every declared route runs, over ``client``."""
    return _ModelEndpoint(
        http_client=client,
        cfg=cfg,
        routes=routes_for(cfg.models),
        tavily_http=None,
        tavily_api_key=None,
    )


def _config(blob_refs: bool | None = None) -> AigatewayConfig:
    """One declared model; ``blob_refs`` set when given, else left at today's default."""
    models: tuple[ModelSpec, ...] = (ModelSpec(id=_MODEL, web_search=False),)
    if blob_refs is None:
        return AigatewayConfig(models=models, default_model=_MODEL)
    return AigatewayConfig(models=models, default_model=_MODEL, blob_refs=blob_refs)


async def _call(handler: _ModelEndpoint, context: str, intent: str = "") -> str:
    """One model call on the declared route."""
    return await handler(Request(path=f"/{_MODEL}", context=context, intent=intent, params={}))


async def test_flag_off_sends_todays_request_byte_for_byte() -> None:
    # INVARIANT: with the flag off a run's requests are exactly the pre-PR ones, run state bound
    # or not: no upload, no token header, the file inline.
    today = _FakeGateway()
    async with today.client() as client:
        assert await _call(_endpoint(client, _config()), _picture_case()) == "42"
    off = _FakeGateway()
    async with off.client() as client:
        with run_case_files():
            assert await _call(_endpoint(client, _config(blob_refs=False)), _picture_case()) == "42"

    (before,) = today.calls
    (after,) = off.calls
    assert off.uploads == []
    assert after.content == before.content
    assert dict(after.headers) == dict(before.headers)
    assert _TOKEN_HEADER not in after.headers
    assert _PNG_URI in after.content.decode()


async def test_one_upload_serves_a_fusions_members_and_synthesizer_with_the_runs_token() -> None:
    # STORY: as the operator of a 5-member Fusion on a picture Benchmark, the file crosses to the
    # gateway once per run; the 6 calls carry a few-byte reference instead of the base64.
    gateway = _FakeGateway()
    async with gateway.client() as client:
        handler: _ModelEndpoint = _endpoint(client, _config(blob_refs=True))
        with run_case_files() as run:
            members: list[str] = await asyncio.gather(
                *(_call(handler, _picture_case()) for _ in range(5))
            )
            synthesis_context: str = json.dumps(
                {"input": _picture_case(), "outputs": {f"member_{n}": "42" for n in range(1, 6)}}
            )
            synthesis: str = await _call(handler, synthesis_context, "Synthesize.")

    assert members == ["42"] * 5 and synthesis == "42"
    (upload,) = gateway.uploads
    assert upload.method == "PUT"
    assert upload.url.path == f"/v1/blobs/sha256/{_PNG_SHA256}"
    assert upload.content == _PNG_BYTES
    assert upload.headers[_TOKEN_HEADER] == run.token
    assert len(gateway.calls) == 6
    for call in gateway.calls:
        assert call.headers[_TOKEN_HEADER] == run.token
        sent: str = call.content.decode()
        assert f"blob:sha256/{_PNG_SHA256}" in sent
        # INVARIANT: no call carries the file's base64 once it travels by reference.
        assert _PNG_URI not in sent


async def test_two_runs_upload_under_two_different_tokens() -> None:
    # INVARIANT (decision 3): another run never shares this run's token, so it cannot use this
    # run's file even when it knows the SHA-256; each run uploads its own copy.
    gateway = _FakeGateway()
    async with gateway.client() as client:
        handler: _ModelEndpoint = _endpoint(client, _config(blob_refs=True))
        for _ in range(2):
            with run_case_files():
                await _call(handler, _picture_case())

    first, second = gateway.uploads
    assert first.headers[_TOKEN_HEADER] != second.headers[_TOKEN_HEADER]
    assert [call.headers[_TOKEN_HEADER] for call in gateway.calls] == [
        first.headers[_TOKEN_HEADER],
        second.headers[_TOKEN_HEADER],
    ]


async def test_every_engine_run_mints_its_own_token() -> None:
    # INVARIANT (decision 3): the run path binds a fresh holder per run (`runner/executor.py`
    # `_drive`), so two runs of one executor never share a token; a text call carries it too.
    gateway = _FakeGateway()
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_MODEL,
            models=(ModelSpec(id=_MODEL, web_search=False),),
            blob_refs=True,
        )
    )
    async with gateway.client() as client:
        executor = build_executor({}, config, client=client)
        for _ in range(2):
            async for _frame in executor.execute(f"/{_MODEL}('ctx')!'go'"):
                pass

    first, second = (call.headers[_TOKEN_HEADER] for call in gateway.calls)
    assert first != second
    assert gateway.uploads == []


async def test_no_upload_route_sends_the_whole_run_inline() -> None:
    # STORY: as an Engine whose gateway predates the upload route, my run sends inline as today.
    gateway = _FakeGateway(upload_status=404)
    async with gateway.client() as client:
        handler: _ModelEndpoint = _endpoint(client, _config(blob_refs=True))
        with run_case_files():
            await _call(handler, _picture_case())
            await _call(handler, _picture_case())

    # The path is chosen once: one upload try, then every call inline, with no token.
    assert len(gateway.uploads) == 1
    for call in gateway.calls:
        assert _PNG_URI in call.content.decode()
        assert _TOKEN_HEADER not in call.headers


async def test_a_refused_upload_fails_the_call_by_the_gateways_code_before_any_chat_call() -> None:
    # WHY permanent: a file over the 15,000,000-byte upload cap would be refused on every try,
    # and it is over the 12 MiB inline cap too, so there is no path that could carry it.
    gateway = _FakeGateway(upload_status=413, upload_code="blob_too_large")
    async with gateway.client() as client:
        handler: _ModelEndpoint = _endpoint(client, _config(blob_refs=True))
        with run_case_files(), pytest.raises(ResolutionError) as refused:
            await _call(handler, _picture_case())

    assert refused.value.code == "blob_too_large"
    assert refused.value.permanent is True
    assert gateway.calls == []


async def test_the_flag_is_off_unless_url4_toml_or_the_chart_turns_it_on() -> None:
    # INVARIANT: off by default; the chart's AIGATEWAY_BLOB_REFS beats the file, as every
    # deploy-time aigateway value does (`config._apply_env`); a typo fails at startup.
    table: dict[str, object] = {"default_route": f"/{_MODEL}"}
    default: WorldConfig = parse_config({"aigateway": table}, {})
    assert default.aigateway is not None and default.aigateway.blob_refs is False
    assert _aigateway_config(default.aigateway).blob_refs is False
    on: WorldConfig = parse_config({"aigateway": {**table, "blob_refs": True}}, {})
    assert on.aigateway is not None and on.aigateway.blob_refs is True
    assert _aigateway_config(on.aigateway).blob_refs is True
    chart_off: WorldConfig = parse_config(
        {"aigateway": {**table, "blob_refs": True}}, {job_env.AIGATEWAY_BLOB_REFS: "false"}
    )
    assert chart_off.aigateway is not None and chart_off.aigateway.blob_refs is False
    chart_on: WorldConfig = parse_config(
        {"aigateway": table}, {job_env.AIGATEWAY_BLOB_REFS: "true"}
    )
    assert chart_on.aigateway is not None and chart_on.aigateway.blob_refs is True
    with pytest.raises(WorldConfigError, match="AIGATEWAY_BLOB_REFS"):
        parse_config({"aigateway": table}, {job_env.AIGATEWAY_BLOB_REFS: "yes"})
