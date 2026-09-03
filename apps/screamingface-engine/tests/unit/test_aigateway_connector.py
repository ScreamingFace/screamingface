from __future__ import annotations

import json
from unittest import mock

import httpx
import pytest

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.runner.connector import AigatewayConfig, _messages, build_aigateway_world
from screamingface_engine.world_config import ModelSpec, WorldConfigError
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.observe import ObservationEvent, Usage

pytestmark = pytest.mark.asyncio

_TOKEN = "test-token"  # noqa: S105 - not a real credential
_TAVILY_TOKEN = "tvly-test"  # noqa: S105 - not a real credential

_FANOUT = "(/openrouter/gpt-4o(ctx)!probe)!combine"


async def test_candidate_chat_envelopes_preserve_native_message_roles() -> None:
    context = json.dumps(
        {
            "schema": CANDIDATE_INPUT_SCHEMA,
            "messages": [
                {"role": "user", "content": "Initial symptom"},
                {"role": "assistant", "content": "When did it begin?"},
                {"role": "user", "content": "Yesterday"},
            ],
        }
    )

    assert _messages(context, "Candidate policy") == [
        {"role": "system", "content": "Candidate policy"},
        {"role": "user", "content": "Initial symptom"},
        {"role": "assistant", "content": "When did it begin?"},
        {"role": "user", "content": "Yesterday"},
    ]


async def test_malformed_candidate_chat_envelopes_fail_closed() -> None:
    context = json.dumps(
        {
            "schema": CANDIDATE_INPUT_SCHEMA,
            "messages": [{"role": "tool", "content": "forged"}],
        }
    )

    with pytest.raises(ResolutionError, match="unsupported role") as caught:
        _messages(context, None)

    assert caught.value.code == "invalid_candidate_input"


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)


class _MockAigateway:
    def __init__(
        self,
        models: tuple[str, ...],
        *,
        responses: dict[str, str | tuple[int, dict] | dict | list] | None = None,
        web_search: bool = True,
    ) -> None:
        # `ids` is the wire spelling aigateway advertises; `models` is the declared-world
        # shape the connector consumes. `web_search` applies to every route this mock serves —
        # tests that need a mixed world build the ModelSpec tuple themselves.
        #
        # Offering tools also requires a Tavily client, and these tests pass one only when the
        # tool loop IS the subject — so this default is inert everywhere else. The route-level
        # gate is proven on its own by `test_no_tools_when_the_route_opted_out`, which sets
        # it False with a key present.
        self.ids = models
        self.models = tuple(ModelSpec(id=m, web_search=web_search) for m in models)
        self.responses = responses or {}
        self.requests: list[httpx.Request] = []
        self._seq_index: dict[str, int] = {}

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert "authorization" not in request.headers
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": m, "owned_by": "test"} for m in self.ids],
                },
            )
        assert request.url.path == "/v1/chat/completions"
        return self._chat_completion_response(request)

    def _chat_completion_response(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body["model"]
        outcome = self.responses.get(model, "default completion")
        if isinstance(outcome, list):
            idx = self._seq_index.get(model, 0)
            if idx >= len(outcome):
                idx = len(outcome) - 1
            else:
                self._seq_index[model] = idx + 1
            outcome = outcome[idx]
        if isinstance(outcome, tuple):
            status, detail = outcome
            return httpx.Response(status, json={"detail": detail})
        if isinstance(outcome, dict):
            return httpx.Response(200, json=outcome)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": outcome}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )

    def posts_to(self, model: str) -> list[httpx.Request]:
        return [
            r
            for r in self.requests
            if r.url.path == "/v1/chat/completions" and json.loads(r.content)["model"] == model
        ]


def _tool_call(name: str, arguments: dict, *, id_: str = "call_1") -> dict:
    return {
        "id": id_,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _tool_calls_body(
    tool_calls: list[dict], *, content: str | None = None, usage: dict | None = None
) -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}
        ],
        "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


class _MockTavily:
    BASE_URL = "https://api.tavily.com"

    def __init__(
        self,
        *,
        search_results: list[dict] | None = None,
        extract_results: list[dict] | None = None,
        extract_failed: list[dict] | None = None,
        search_status: int = 200,
        extract_status: int = 200,
        search_error: str = "boom",
        extract_error: str = "boom",
    ) -> None:
        self.search_results = search_results if search_results is not None else []
        self.extract_results = extract_results if extract_results is not None else []
        self.extract_failed = extract_failed if extract_failed is not None else []
        self.search_status = search_status
        self.extract_status = extract_status
        self.search_error = search_error
        self.extract_error = extract_error
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"] == f"Bearer {_TAVILY_TOKEN}"
        if request.url.path == "/search":
            return self._search_response()
        assert request.url.path == "/extract"
        return self._extract_response()

    def _search_response(self) -> httpx.Response:
        if self.search_status != 200:
            return httpx.Response(self.search_status, json={"detail": {"error": self.search_error}})
        return httpx.Response(200, json={"results": self.search_results, "response_time": 0.1})

    def _extract_response(self) -> httpx.Response:
        if self.extract_status != 200:
            return httpx.Response(
                self.extract_status, json={"detail": {"error": self.extract_error}}
            )
        return httpx.Response(
            200,
            json={
                "results": self.extract_results,
                "failed_results": self.extract_failed,
                "response_time": 0.1,
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url=self.BASE_URL
        )

    def posts_to(self, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == path]


async def test_declared_models_register_routes_one_to_one() -> None:
    gw = _MockAigateway(("anthropic/claude-haiku-4-5", "openrouter/gpt-4o"))
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        assert set(world.node.processor_routes()) == {
            "/anthropic/claude-haiku-4-5",
            "/openrouter/gpt-4o",
        }


async def test_the_world_never_asks_the_gateway_for_its_catalog() -> None:
    # Endpoints are DECLARED. A `/v1/models` call here would mean routes can change under an
    # expression between runs — the property the declared config exists to remove.
    gw = _MockAigateway(("anthropic/claude-haiku-4-5",))
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        await build_aigateway_world(cfg, client=client)

    assert not any(r.url.path == "/v1/models" for r in gw.requests)


async def test_no_bare_alias_is_registered_for_a_prefixed_id() -> None:
    # The alias this replaces turned `openrouter/openai/gpt-5.5` into `/openai/gpt-5.5`, which
    # reads as the OpenAI API while billing OpenRouter.
    gw = _MockAigateway(("openrouter/openai/gpt-5.5", "codex/gpt-5.5"))
    cfg = AigatewayConfig(models=gw.models, default_model="codex/gpt-5.5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        assert set(world.node.processor_routes()) == {
            "/openrouter/openai/gpt-5.5",
            "/codex/gpt-5.5",
        }


async def test_a_bare_short_name_no_longer_resolves_to_a_prefixed_model() -> None:
    gw = _MockAigateway(("codex/gpt-5.5",))
    cfg = AigatewayConfig(models=gw.models, default_model="codex/gpt-5.5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        fanout = "(/codex/gpt-5.5(ctx)!probe)!combine"
        with pytest.raises(ResolutionError) as exc_info:
            await url4_run(fanout, io=world.node, processor="gpt-5.5")

    assert exc_info.value.code == "unknown_processor"


@pytest.mark.parametrize(
    "processor_value",
    ["/anthropic/claude-haiku-4-5", "anthropic/claude-haiku-4-5"],
)
async def test_both_qualified_processor_forms_select_the_named_model(
    processor_value: str,
) -> None:
    gw = _MockAigateway(("anthropic/claude-haiku-4-5", "openrouter/gpt-4o"))
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        await url4_run(_FANOUT, io=world.node, processor=processor_value)

        assert len(gw.posts_to("anthropic/claude-haiku-4-5")) == 1
        assert len(gw.posts_to("openrouter/gpt-4o")) == 1


async def test_bare_reduce_with_no_processor_uses_the_default_model() -> None:
    gw = _MockAigateway(("anthropic/claude-haiku-4-5", "openrouter/gpt-4o"))
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        await url4_run(_FANOUT, io=world.node)

        assert len(gw.posts_to("anthropic/claude-haiku-4-5")) == 1


async def test_handler_returns_the_completion_content() -> None:
    gw = _MockAigateway(
        ("anthropic/claude-haiku-4-5",),
        responses={"anthropic/claude-haiku-4-5": "hello there"},
    )
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        result = await url4_run("/anthropic/claude-haiku-4-5(ctx)!go", io=world.node)

        assert result == "hello there"


async def test_usage_is_reported_for_this_route_via_the_engine_observer() -> None:
    gw = _MockAigateway(("anthropic/claude-haiku-4-5",))
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    recorder = _Recorder()
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        await url4_run("/anthropic/claude-haiku-4-5(ctx)!go", io=world.node, observer=recorder)

    usage_events = [e for e in recorder.events if isinstance(e, Usage)]
    assert len(usage_events) == 1
    usage = usage_events[0]
    assert usage.provider == "anthropic"
    assert usage.model == "anthropic/claude-haiku-4-5"
    assert usage.input_tokens == 11
    assert usage.output_tokens == 7


async def test_usage_provider_is_anthropic_for_a_bare_unprefixed_model() -> None:
    gw = _MockAigateway(("claude-haiku-4-5",))
    cfg = AigatewayConfig(models=gw.models, default_model="claude-haiku-4-5")
    recorder = _Recorder()
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        await url4_run("/claude-haiku-4-5(ctx)!go", io=world.node, observer=recorder)

    usage_events = [e for e in recorder.events if isinstance(e, Usage)]
    assert len(usage_events) == 1
    assert usage_events[0].provider == "anthropic"
    assert usage_events[0].model == "claude-haiku-4-5"


async def test_a_shared_bare_name_across_providers_stays_addressable_by_full_id() -> None:
    gw = _MockAigateway(("anthropic/x", "openrouter/x"))
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/x")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        assert set(world.node.processor_routes()) == {"/anthropic/x", "/openrouter/x"}

        fanout = "(/anthropic/x(ctx)!probe)!combine"
        with pytest.raises(ResolutionError) as exc_info:
            await url4_run(fanout, io=world.node, processor="x")

    assert exc_info.value.code == "unknown_processor"


async def test_unregistered_model_id_fails_before_any_completion_call() -> None:
    gw = _MockAigateway(("anthropic/claude-haiku-4-5",))
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        fanout = "(/anthropic/claude-haiku-4-5(ctx)!probe)!combine"
        with pytest.raises(ResolutionError) as exc_info:
            await url4_run(fanout, io=world.node, processor="not-a-real-model")

    assert exc_info.value.code == "unknown_processor"
    assert gw.posts_to("not-a-real-model") == []
    assert len(gw.posts_to("anthropic/claude-haiku-4-5")) == 1


@pytest.mark.parametrize(
    ("status", "detail", "expected_permanent"),
    [
        (401, {"code": "invalid_credential", "message": "bad token"}, True),
        (402, {"code": "quota_exceeded", "message": "no budget"}, True),
        (429, {"code": "rate_limited", "message": "slow down"}, False),
        (503, {"code": "upstream_unavailable", "message": "down"}, False),
    ],
)
async def test_aigateway_http_errors_map_to_resolution_error(
    status: int, detail: dict, expected_permanent: bool
) -> None:
    gw = _MockAigateway(
        ("anthropic/claude-haiku-4-5",),
        responses={"anthropic/claude-haiku-4-5": (status, detail)},
    )
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        with pytest.raises(ResolutionError) as exc_info:
            await url4_run("/anthropic/claude-haiku-4-5(ctx)!go", io=world.node)

    assert exc_info.value.code == detail["code"]
    assert exc_info.value.permanent is expected_permanent


async def test_aigateway_transport_errors_map_to_retryable_resolution_error() -> None:
    """A transport failure (connection reset / read error) is retryable and named.

    WHY (OME-1016): a raw ``httpx.ReadError`` bypasses the benchmark's declared ``retry=``
    policy (url4 retries only ``Url4Error``) and carries no error ``code``, so the report
    would fall back to the opaque benchmark default (``draco_grading_failed``) with a
    useless ``ReadError('')`` message. The connector must translate it into a retryable
    ``ResolutionError`` with a non-empty message.
    """

    def _drop_connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_drop_connection),
        base_url="http://aigateway.test",
    ) as client:
        cfg = AigatewayConfig(
            models=(ModelSpec(id="anthropic/claude-haiku-4-5"),),
            default_model="anthropic/claude-haiku-4-5",
        )
        world = await build_aigateway_world(cfg, client=client)

        with (
            mock.patch("screamingface_engine.runner.connector._TRANSPORT_BACKOFF_BASE_S", 0.0),
            mock.patch("screamingface_engine.runner.connector._TRANSPORT_BACKOFF_MAX_S", 0.0),
            mock.patch("screamingface_engine.runner.connector._TRANSPORT_BACKOFF_JITTER_S", 0.0),
        ):
            with pytest.raises(ResolutionError) as exc_info:
                await url4_run("/anthropic/claude-haiku-4-5(ctx)!go", io=world.node)

    assert exc_info.value.code == "aigateway_transport_error"
    assert exc_info.value.permanent is False
    assert "ReadError" in str(exc_info.value)
    assert str(exc_info.value).strip()


async def test_aigateway_transport_error_is_retried_then_succeeds() -> None:
    """A transient transport failure is retried once (backoff) and the call succeeds.

    WHY (OME-1016): the connector retries ``httpx.TransportError`` with backoff before
    surfacing a retryable error, so a stale keep-alive connection or a brief aigateway
    blip costs one extra attempt instead of a failed Case.
    """
    posts = 0

    def _flaky(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        if posts == 1:
            raise httpx.ReadError("")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello there"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_flaky),
        base_url="http://aigateway.test",
    ) as client:
        cfg = AigatewayConfig(
            models=(ModelSpec(id="anthropic/claude-haiku-4-5"),),
            default_model="anthropic/claude-haiku-4-5",
        )
        world = await build_aigateway_world(cfg, client=client)

        with (
            mock.patch("screamingface_engine.runner.connector._TRANSPORT_BACKOFF_BASE_S", 0.0),
            mock.patch("screamingface_engine.runner.connector._TRANSPORT_BACKOFF_MAX_S", 0.0),
            mock.patch("screamingface_engine.runner.connector._TRANSPORT_BACKOFF_JITTER_S", 0.0),
        ):
            result = await url4_run("/anthropic/claude-haiku-4-5(ctx)!go", io=world.node)

    assert result == "hello there"
    assert posts == 2


async def test_default_model_must_be_one_of_the_declared_models() -> None:
    gw = _MockAigateway(("openrouter/gpt-4o",))
    cfg = AigatewayConfig(
        default_model="anthropic/claude-haiku-4-5", models=(ModelSpec(id="openrouter/gpt-4o"),)
    )
    async with gw.client() as client:
        with pytest.raises(WorldConfigError, match="anthropic/claude-haiku-4-5"):
            await build_aigateway_world(cfg, client=client)


async def test_owned_client_is_created_and_closed_by_aclose() -> None:
    cfg = AigatewayConfig(
        default_model="anthropic/claude-haiku-4-5",
        models=(ModelSpec(id="anthropic/claude-haiku-4-5"),),
    )

    world = await build_aigateway_world(cfg)

    assert world._owns_client is True
    assert world._client.is_closed is False

    await world.aclose()

    assert world._client.is_closed is True


async def test_injected_client_is_not_closed_by_aclose() -> None:
    gw = _MockAigateway(("anthropic/claude-haiku-4-5",))
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        assert world._owns_client is False

        await world.aclose()

        assert client.is_closed is False


async def test_a_bad_default_model_is_rejected_before_any_client_is_created() -> None:
    # The config is self-describing, so this is decidable without touching the network —
    # validate first and there is no half-built world to leak.
    cfg = AigatewayConfig(
        default_model="not/in-catalog", models=(ModelSpec(id="anthropic/claude-haiku-4-5"),)
    )
    created: list[bool] = []
    real_init = httpx.AsyncClient.__init__

    def _spy_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        created.append(True)
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    with (
        mock.patch.object(httpx.AsyncClient, "__init__", _spy_init),
        pytest.raises(WorldConfigError, match="not/in-catalog"),
    ):
        await build_aigateway_world(cfg)

    assert created == []


async def test_declaring_no_models_is_a_config_error() -> None:
    with pytest.raises(WorldConfigError, match="declares no models"):
        await build_aigateway_world(AigatewayConfig(models=()))


async def test_malformed_completion_response_raises_resolution_error() -> None:
    gw = _MockAigateway(
        ("anthropic/claude-haiku-4-5",), responses={"anthropic/claude-haiku-4-5": {}}
    )
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        with pytest.raises(ResolutionError) as exc_info:
            await url4_run("/anthropic/claude-haiku-4-5(ctx)!go", io=world.node)

    assert exc_info.value.code == "aigateway_bad_response"
    assert exc_info.value.permanent is True


# A malformed `/v1/models` response is no longer a failure mode the Runner has: the catalog
# fetch is gone, so a broken gateway registry cannot change which routes this world serves.


async def test_no_usage_block_reports_no_usage_event_but_still_returns_content() -> None:
    gw = _MockAigateway(
        ("anthropic/claude-haiku-4-5",),
        responses={
            "anthropic/claude-haiku-4-5": {"choices": [{"message": {"content": "no usage here"}}]}
        },
    )
    cfg = AigatewayConfig(models=gw.models, default_model="anthropic/claude-haiku-4-5")
    recorder = _Recorder()
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        result = await url4_run(
            "/anthropic/claude-haiku-4-5(ctx)!go", io=world.node, observer=recorder
        )

    assert result == "no usage here"
    assert [e for e in recorder.events if isinstance(e, Usage)] == []


_MODEL = "anthropic/claude-haiku-4-5"


async def test_no_tools_when_tavily_key_absent() -> None:
    # The route opts IN, so the absent key is the only thing that can withhold the tools.
    gw = _MockAigateway((_MODEL,), responses={_MODEL: "plain answer"}, web_search=True)
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        assert world.web_tools_enabled is False
        await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    body = json.loads(gw.posts_to(_MODEL)[0].content)
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_no_tools_when_the_route_opted_out() -> None:
    # The other half of the gate: a configured Tavily key must NOT rewrite the request of a
    # model whose route declares `web_search=False`. Without this, supplying a key to serve one
    # route would silently change what every other model is asked.
    gw = _MockAigateway((_MODEL,), responses={_MODEL: "plain answer"}, web_search=False)
    tvly = _MockTavily()
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        # The WORLD can serve web tools; this ROUTE still does not ask for them.
        assert world.web_tools_enabled is True
        await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    body = json.loads(gw.posts_to(_MODEL)[0].content)
    assert "tools" not in body
    assert "tool_choice" not in body
    assert tvly.requests == []


async def test_opted_in_and_opted_out_routes_coexist_in_one_world() -> None:
    # The point of a per-ROUTE flag: one world, two behaviors, decided by the declaration.
    plain, searcher = "anthropic/plain", "anthropic/searcher"
    gw = _MockAigateway((plain, searcher), responses={plain: "a", searcher: "b"})
    tvly = _MockTavily()
    cfg = AigatewayConfig(
        models=(ModelSpec(id=plain, web_search=False), ModelSpec(id=searcher, web_search=True)),
        default_model=plain,
    )
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        await url4_run(f"/{plain}(ctx)!go", io=world.node)
        await url4_run(f"/{searcher}(ctx)!go", io=world.node)

    assert "tools" not in json.loads(gw.posts_to(plain)[0].content)
    assert "tools" in json.loads(gw.posts_to(searcher)[0].content)


async def test_tools_declared_when_tavily_key_present() -> None:
    gw = _MockAigateway((_MODEL,), responses={_MODEL: "plain answer"})
    tvly = _MockTavily()
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        assert world.web_tools_enabled is True
        await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    body = json.loads(gw.posts_to(_MODEL)[0].content)
    tool_names = {t["function"]["name"] for t in body["tools"]}
    assert tool_names == {"web_search", "web_fetch"}
    assert body["tool_choice"] == "auto"
    assert tvly.requests == []


async def test_web_search_loop_executes_tavily_search_then_answers() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body([_tool_call("web_search", {"query": "who is leo"})]),
                "Leo is a footballer.",
            ]
        },
    )
    tvly = _MockTavily(
        search_results=[
            {"title": "Messi", "url": "https://w/M", "content": "Leo plays football."},
            {"title": "Wiki", "url": "https://w/L", "content": "Born 1987."},
        ]
    )
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert result == "Leo is a footballer."
    assert len(gw.posts_to(_MODEL)) == 2
    assert len(tvly.posts_to("/search")) == 1
    tavily_body = json.loads(tvly.posts_to("/search")[0].content)
    assert tavily_body["query"] == "who is leo"
    assert tavily_body["search_depth"] == "advanced"
    assert tavily_body["max_results"] == 5
    round2_messages = json.loads(gw.posts_to(_MODEL)[1].content)["messages"]
    assert round2_messages[-1]["role"] == "tool"
    assert round2_messages[-1]["tool_call_id"] == "call_1"
    assert "Messi" in round2_messages[-1]["content"]
    assert round2_messages[-2]["role"] == "assistant"
    assert round2_messages[-2]["tool_calls"][0]["function"]["name"] == "web_search"


async def test_web_fetch_loop_executes_tavily_extract_then_answers() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body([_tool_call("web_fetch", {"url": "https://x/page"})]),
                "The page is about cats.",
            ]
        },
    )
    tvly = _MockTavily(extract_results=[{"url": "https://x/page", "raw_content": "# Cats"}])
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert result == "The page is about cats."
    assert len(tvly.posts_to("/extract")) == 1
    extract_body = json.loads(tvly.posts_to("/extract")[0].content)
    assert extract_body["urls"] == "https://x/page"
    assert extract_body["format"] == "markdown"
    round2_messages = json.loads(gw.posts_to(_MODEL)[1].content)["messages"]
    assert round2_messages[-1]["content"] == "# Cats"


async def test_parallel_tool_calls_both_executed_in_one_turn() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body(
                    [
                        _tool_call("web_search", {"query": "q1"}, id_="c_search"),
                        _tool_call("web_fetch", {"url": "https://x"}, id_="c_fetch"),
                    ]
                ),
                "merged answer",
            ]
        },
    )
    tvly = _MockTavily(
        search_results=[{"title": "S", "url": "https://s", "content": "sc"}],
        extract_results=[{"url": "https://x", "raw_content": "xc"}],
    )
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert result == "merged answer"
    assert len(tvly.posts_to("/search")) == 1
    assert len(tvly.posts_to("/extract")) == 1
    round2_messages = json.loads(gw.posts_to(_MODEL)[1].content)["messages"]
    tool_results = [m for m in round2_messages if m.get("role") == "tool"]
    assert [t["tool_call_id"] for t in tool_results] == ["c_search", "c_fetch"]


async def test_usage_accumulates_across_round_trips_on_same_span() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body(
                    [_tool_call("web_search", {"query": "q"})],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                ),
                {
                    "choices": [{"message": {"content": "done"}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
                },
            ]
        },
    )
    tvly = _MockTavily(search_results=[{"title": "S", "url": "https://s", "content": "c"}])
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    recorder = _Recorder()
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=recorder)

    usage_events = [e for e in recorder.events if isinstance(e, Usage)]
    assert len(usage_events) == 2
    assert {e.span_id for e in usage_events} == {usage_events[0].span_id}
    assert sum(e.input_tokens for e in usage_events) == 30
    assert sum(e.output_tokens for e in usage_events) == 13


async def test_tavily_http_failure_fed_back_to_model_not_raised() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body([_tool_call("web_search", {"query": "q"})]),
                "I could not find anything.",
            ]
        },
    )
    tvly = _MockTavily(search_status=500, search_error="upstream down")
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert result == "I could not find anything."
    round2_messages = json.loads(gw.posts_to(_MODEL)[1].content)["messages"]
    assert round2_messages[-1]["role"] == "tool"
    assert "web_search failed" in round2_messages[-1]["content"]


async def test_unknown_tool_name_fed_back_to_model() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body([_tool_call("calc", {"x": 1})]),
                "I can't calculate.",
            ]
        },
    )
    tvly = _MockTavily()
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert result == "I can't calculate."
    round2_messages = json.loads(gw.posts_to(_MODEL)[1].content)["messages"]
    assert round2_messages[-1]["content"] == "unknown tool: calc"


async def test_invalid_tool_arguments_fed_back_to_model() -> None:
    bad_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "web_search", "arguments": "not-json"},
    }
    gw = _MockAigateway(
        (_MODEL,),
        responses={_MODEL: [_tool_calls_body([bad_call]), "recovered."]},
    )
    tvly = _MockTavily()
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert result == "recovered."
    round2_messages = json.loads(gw.posts_to(_MODEL)[1].content)["messages"]
    assert round2_messages[-1]["content"] == "invalid arguments for web_search"


async def test_max_iterations_exceeded_raises_resolution_error() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={_MODEL: [_tool_calls_body([_tool_call("web_search", {"query": "q"})])]},
    )
    tvly = _MockTavily(search_results=[{"title": "S", "url": "https://s", "content": "c"}])
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL, web_tool_max_iterations=2)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        with pytest.raises(ResolutionError) as exc_info:
            await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert exc_info.value.code == "web_tool_loop_limit"
    assert exc_info.value.permanent is False
    assert len(gw.posts_to(_MODEL)) == 2


async def test_extract_content_tolerates_content_none_with_tool_calls() -> None:
    body_with_tools = {
        "choices": [
            {"message": {"content": None, "tool_calls": [_tool_call("web_search", {"query": "q"})]}}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    gw = _MockAigateway((_MODEL,), responses={_MODEL: [body_with_tools, "final."]})
    tvly = _MockTavily(search_results=[{"title": "S", "url": "https://s", "content": "c"}])
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert result == "final."


async def test_malformed_neither_content_nor_tool_calls_still_raises() -> None:
    gw = _MockAigateway((_MODEL,), responses={_MODEL: {"choices": [{"message": {}}]}})
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        with pytest.raises(ResolutionError) as exc_info:
            await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert exc_info.value.code == "aigateway_bad_response"
    assert exc_info.value.permanent is True


async def test_owned_tavily_client_closed_on_aclose() -> None:
    cfg = AigatewayConfig(default_model=_MODEL, models=(ModelSpec(id=_MODEL),))
    world = await build_aigateway_world(cfg, tavily_api_key=_TAVILY_TOKEN)

    assert world._owns_tavily_client is True
    assert world._tavily_client is not None
    assert world._tavily_client.is_closed is False

    await world.aclose()

    assert world._tavily_client.is_closed is True
    assert world._client.is_closed is True


async def test_injected_tavily_client_not_closed_on_aclose() -> None:
    gw = _MockAigateway((_MODEL,))
    tvly = _MockTavily()
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        assert world._owns_tavily_client is False

        await world.aclose()

        assert tclient.is_closed is False
        assert client.is_closed is False


async def test_tavily_search_formats_results_as_title_url_content_blocks() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body([_tool_call("web_search", {"query": "q"})]),
                "done",
            ]
        },
    )
    tvly = _MockTavily(
        search_results=[
            {"title": "T1", "url": "https://u1", "content": "C1"},
            {"title": "T2", "url": "https://u2", "content": "C2"},
        ]
    )
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    tool_result = json.loads(gw.posts_to(_MODEL)[1].content)["messages"][-1]["content"]
    assert "Title: T1\nURL: https://u1\nContent: C1" in tool_result
    assert "Title: T2\nURL: https://u2\nContent: C2" in tool_result


async def test_tavily_extract_reports_failed_urls_in_tool_result() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body([_tool_call("web_fetch", {"url": "https://blocked"})]),
                "give up.",
            ]
        },
    )
    tvly = _MockTavily(
        extract_results=[],
        extract_failed=[{"url": "https://blocked", "error": "403 forbidden"}],
    )
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    tool_result = json.loads(gw.posts_to(_MODEL)[1].content)["messages"][-1]["content"]
    assert "https://blocked" in tool_result
    assert "403 forbidden" in tool_result


async def test_tavily_key_never_sent_to_aigateway() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: [
                _tool_calls_body([_tool_call("web_search", {"query": "q"})]),
                "done",
            ]
        },
    )
    tvly = _MockTavily(search_results=[{"title": "S", "url": "https://s", "content": "c"}])
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client, tvly.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_TAVILY_TOKEN, tavily_client=tclient
        )

        await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    for req in gw.posts_to(_MODEL):
        assert "authorization" not in req.headers
        assert _TAVILY_TOKEN not in str(req.headers) + req.content.decode("utf-8", errors="ignore")


async def test_a_tool_result_is_capped_before_it_re_enters_the_prompt() -> None:
    """A tool result is appended to `messages` and re-sent on EVERY later iteration, so an
    uncapped one is paid for repeatedly and can exceed the model's context outright."""
    from screamingface_engine.runner.connector import _truncate_tool_result

    out = _truncate_tool_result("x" * 100_000, 1000)

    assert len(out.encode("utf-8")) <= 1000
    assert out.endswith("…[truncated]"), "a silent cut reads to the model as a complete document"


async def test_a_short_tool_result_is_left_exactly_alone() -> None:
    from screamingface_engine.runner.connector import _truncate_tool_result

    assert _truncate_tool_result("small", 1000) == "small"


async def test_truncation_never_splits_a_multibyte_character() -> None:
    """The cap is in BYTES but the value must stay valid UTF-8 — a split character would raise on
    encode at the next request rather than at the cut."""
    from screamingface_engine.runner.connector import _truncate_tool_result

    out = _truncate_tool_result("é" * 5000, 137)

    assert len(out.encode("utf-8")) <= 137
    out.encode("utf-8").decode("utf-8")  # must not raise
