"""The local runtime's Gateway counts every physical LiteLLM send into its attempt header.

Mental model: ``screamingface up`` serves the AI Gateway from this checkout on the ``[runtime]``
extra's own LiteLLM pin, not on the Gateway app's lock. The Gateway proves its
``X-AIGW-Upstream-Attempts`` header (contract C7) under its own lock; this proves the same seam on
the runtime's pin, through the runtime's own boot: source activation, migrations, the app build
and the embedded uvicorn server.

FEATURE: Router Recipe extension Unit 5.1, test-plan §4 item 8, on the SDK runtime. HuggingFace
and Ollama hand the injected client to LiteLLM's base handler: one physical send reads ``1`` and
LiteLLM's hidden resend after a connect error reads ``2``, with usage accounting on and off.
WHY one fresh interpreter per accounting mode: the runtime imports the Gateway once per process,
which reads the accounting switch when its app starts. The probe is this file run as a script,
so the code that boots the runtime is linted and type-checked like the assertions.
WHY only the physical transport is fake: every client property stays real, so the hidden resend
and its replacement client run as in production while no request leaves the machine. Key
readiness and Ollama's model listing would dial a provider and get offline doubles.
INVARIANT: a header that disagrees with the sends the fake transport saw fails the check. A false
``0`` is a failed gate, never an adjusted expectation.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tomllib
from collections.abc import Callable
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
from typing import Any, TypedDict

import httpx
import pytest
from harness._gating import E2E_ENV

pytestmark = pytest.mark.e2e

HEADER = "x-aigw-upstream-attempts"
CHAT = "/v1/chat/completions"
OLLAMA_HOST = "http://localhost:11434"
MODELS = {
    "huggingface": "huggingface/deepseek-ai/DeepSeek-R1:novita",
    "ollama": "ollama/llama3.2:1b",
}
# WHY exact URLs: each proves the send was the provider's own request, made through the fake.
SEND_URLS = {
    "huggingface": "https://router.huggingface.co/v1/chat/completions",
    "ollama": f"{OLLAMA_HOST}/api/chat",
}
ANSWER = {"role": "assistant", "content": "ok"}
REPLIES: dict[str, dict[str, Any]] = {
    "huggingface": {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "message": ANSWER, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    },
    "ollama": {
        "model": "llama3.2:1b",
        "created_at": "2026-01-01T00:00:00Z",
        "message": ANSWER,
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 1,
        "eval_count": 1,
    },
}
PROVIDERS = tuple(MODELS)
ACCOUNTING = ("on", "off")
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
# WHY tolerated, and only refused: for a HuggingFace model absent from its map, LiteLLM's model-info
# helper (`_get_max_position_embeddings`) fetches its public config.json here with its own sync
# client, on the runtime's and the Gateway's pins alike. That is metadata, not the call's upstream
# send, so C7 does not count it; the probe refuses it and LiteLLM reads the failure as unknown.
METADATA_LOOKUP_HOSTS = frozenset({"huggingface.co"})
# WHY dropped from the probe's environment: an operator's exported Gateway settings, provider
# hosts or keys must neither steer the probe nor reach it. The runtime adds its own defaults.
FOREIGN_PREFIXES = ("AIGW_", "AIGATEWAY_", "LITELLM_", "OLLAMA_", "HF_", "HUGGINGFACE")
FOREIGN_SUFFIXES = ("_API_KEY", "_TOKEN")
SDK_LOCK = Path(__file__).resolve().parents[2] / "uv.lock"

Responder = Callable[[httpx.Request], httpx.Response]
Report = dict[str, Any]


class Exchange(TypedDict):
    """One chat call as the caller saw it, beside the physical sends the fake transport saw."""

    status: int
    header: str | None
    urls: list[str]
    detail: str


def verify_attempts(exchange: Exchange, sends: int) -> None:
    """Accept only a served answer whose header names exactly the physical sends observed."""
    assert exchange["status"] == 200, exchange
    assert len(exchange["urls"]) == sends, exchange
    assert exchange["header"] == str(sends), exchange


# --- the probe: runs in a fresh interpreter, see `_probe` --------------------------------------


class FakeTransport:
    """Every client LiteLLM builds sends here; ``sent`` holds each physical request."""

    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []
        self.respond: Responder = lambda _request: httpx.Response(500)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        return self.respond(request)


def _reply(payload: dict[str, Any]) -> Responder:
    return lambda _request: httpx.Response(200, json=payload)


def _connect_error_then(payload: dict[str, Any]) -> Responder:
    """The first send fails to connect; LiteLLM's hidden resend gets ``payload``."""
    sends: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sends.append(request)
        if len(sends) == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=payload)

    return respond


def _refuse_remote_names(patches: pytest.MonkeyPatch) -> list[str]:
    """Fail every name lookup that would leave this machine, and remember the name."""
    refused: list[str] = []
    resolve = socket.getaddrinfo

    def guarded(host: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else host
        if name is not None and name not in LOOPBACK:
            refused.append(str(name))
            raise socket.gaierror(socket.EAI_NONAME, f"offline probe refused {name}")
        return resolve(host, *args, **kwargs)

    patches.setattr(socket, "getaddrinfo", guarded)
    return refused


def _install_seam(patches: pytest.MonkeyPatch) -> tuple[FakeTransport, Callable[..., Any]]:
    """Fake LiteLLM's physical transport and refuse its own client; return that client factory.

    WHY the refusal: LiteLLM falls back to its own cached client when it ignores the ``client``
    it was given, so refusing the fallback proves each counted send went through the Gateway's
    injection. The negative control restores the factory to show what an unobserved send reads.
    """
    from litellm.llms.custom_httpx import (  # pyright: ignore[reportMissingImports]
        http_handler,
        llm_http_handler,
    )

    fake = FakeTransport()

    def transport(
        ssl_context: Any = None, ssl_verify: Any = None, shared_session: Any = None
    ) -> httpx.MockTransport:
        del ssl_context, ssl_verify, shared_session
        return httpx.MockTransport(fake.handle)

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("LiteLLM ignored the injected client")

    handler = http_handler.AsyncHTTPHandler
    patches.setattr(handler, "_create_async_transport", staticmethod(transport))
    patches.setattr(llm_http_handler, "get_async_httpx_client", refuse)
    return fake, http_handler.get_async_httpx_client


def _install_offline_doubles(patches: pytest.MonkeyPatch) -> None:
    from aigateway.core.api_key_validation import (  # pyright: ignore[reportMissingImports]
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import (  # pyright: ignore[reportMissingImports]
        ApiKeyValidationService,
    )
    from aigateway.plugins.ollama_provider import (  # pyright: ignore[reportMissingImports]
        plugin as ollama_plugin,
    )

    async def valid(_self: Any, _plugin: Any, _provider: str, _api_key: str) -> Any:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    installed = MODELS["ollama"].split("/", 1)[1]
    patches.setattr(ApiKeyValidationService, "validate", valid)
    patches.setattr(ollama_plugin, "discover_ollama_models", lambda _host: [installed])


def _lift_the_seam(patches: pytest.MonkeyPatch, own_client: Callable[..., Any]) -> None:
    """The negative control: the Gateway stops injecting, so LiteLLM sends through its own client.

    That client still runs on the fake transport: the send is served and seen, unobserved.
    """
    from aigateway.routes import chat  # pyright: ignore[reportMissingImports]
    from litellm.llms.custom_httpx import llm_http_handler  # pyright: ignore[reportMissingImports]

    patches.setattr(chat, "dispatch_body_with_accounting", lambda body, *_args: body)
    patches.setattr(chat, "with_observed_litellm_client", lambda body, **_kwargs: body)
    patches.setattr(llm_http_handler, "get_async_httpx_client", own_client)


async def _chat(
    client: httpx.AsyncClient, fake: FakeTransport, provider: str, respond: Responder, case: str
) -> Exchange:
    fake.sent.clear()
    fake.respond = respond
    # WHY one prompt per case: the runtime caches by default, and a cache hit honestly reads 0.
    prompt = f"attempt proof: {provider} {case}"
    body = {"model": MODELS[provider], "messages": [{"role": "user", "content": prompt}]}
    response = await client.post(CHAT, json=body)
    return {
        "status": response.status_code,
        "header": response.headers.get(HEADER),
        "urls": [str(request.url) for request in fake.sent],
        "detail": "" if response.status_code == 200 else response.text[:500],
    }


async def _exchanges(
    client: httpx.AsyncClient,
    fake: FakeTransport,
    patches: pytest.MonkeyPatch,
    own_client: Callable[..., Any],
) -> dict[str, Exchange]:
    created = await client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "huggingface", "label": "attempt-proof", "api_key": "hf-offline-key"},
    )
    assert created.status_code == 201, created.text
    exchanges: dict[str, Exchange] = {}
    for provider in PROVIDERS:
        reply = REPLIES[provider]
        exchanges[f"{provider}/one"] = await _chat(client, fake, provider, _reply(reply), "one")
        exchanges[f"{provider}/resend"] = await _chat(
            client, fake, provider, _connect_error_then(reply), "resend"
        )
    _lift_the_seam(patches, own_client)
    for provider in PROVIDERS:
        exchanges[f"{provider}/unobserved"] = await _chat(
            client, fake, provider, _reply(REPLIES[provider]), "unobserved"
        )
    return exchanges


async def _serve_and_exchange(
    config: Any, fake: FakeTransport, patches: pytest.MonkeyPatch, own_client: Callable[..., Any]
) -> dict[str, Exchange]:
    """The runtime's own steps after its import guard: migrate, build, serve on loopback."""
    from screamingface._runtime import server

    await server._migrate(config)
    gateway, engine, _summary = server._build_apps(config)
    assert engine is None, "the probe serves the Gateway alone"
    served = server._server(gateway, config.gateway_port, "AI Gateway")
    serving = asyncio.create_task(served.serve())
    try:
        while not served.started:
            if serving.done():
                serving.result()
                raise RuntimeError("the Gateway stopped before it started")
            await asyncio.sleep(0.05)
        base_url = f"http://127.0.0.1:{config.gateway_port}"
        async with httpx.AsyncClient(base_url=base_url, timeout=120) as client:
            return await _exchanges(client, fake, patches, own_client)
    finally:
        served.should_exit = True
        await serving


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _probe(data_dir: Path) -> None:
    """Boot the runtime's Gateway offline, drive every case, print one JSON report line."""
    patches = pytest.MonkeyPatch()
    # WHY first: the runtime's imports are the earliest point a lookup could leave the machine.
    refused = _refuse_remote_names(patches)
    from screamingface._runtime.bootstrap import pin_litellm_redaction
    from screamingface._runtime.config import RuntimeConfig
    from screamingface._runtime.server import require_runtime_extra

    source = require_runtime_extra()  # what `run` does first: live source, then the app imports
    pin_litellm_redaction()
    fake, own_client = _install_seam(patches)
    _install_offline_doubles(patches)
    # WHY an Engine interpreter: `_build_apps` then builds the Gateway alone, as `up` does.
    config = RuntimeConfig(
        data_dir=data_dir, gateway_port=_free_port(), engine_python=Path(sys.executable)
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    exchanges = asyncio.run(_serve_and_exchange(config, fake, patches, own_client))
    import aigateway  # pyright: ignore[reportMissingImports]

    report = {
        "litellm": version("litellm"),
        "gateway": str(Path(aigateway.__file__).resolve()),
        "source_mode": source.mode,
        "source_root": str(source.root),
        "refused": refused,
        "exchanges": exchanges,
    }
    print(json.dumps(report), flush=True)


# --- the test ------------------------------------------------------------------------------------


def _probe_environment(accounting: str) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(FOREIGN_PREFIXES) and not name.endswith(FOREIGN_SUFFIXES)
    }
    environment["AIGW_TAXONOMY_ENABLED"] = "true" if accounting == "on" else "false"
    environment["AIGW_OLLAMA_HOST"] = OLLAMA_HOST
    return environment


def _run_probe(work_dir: Path, accounting: str) -> Report:
    # WHY cwd: the Gateway's settings read a `.env` from the working directory.
    result = subprocess.run(
        [sys.executable, __file__, str(work_dir / "data")],
        cwd=work_dir,
        env=_probe_environment(accounting),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        pytest.fail(f"the runtime probe failed (accounting {accounting}):\n{result.stderr[-4000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _locked_version(package: str) -> str:
    lock = tomllib.loads(SDK_LOCK.read_text(encoding="utf-8"))
    return next(entry["version"] for entry in lock["package"] if entry["name"] == package)


@pytest.fixture(scope="module")
def reports(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Report]:
    """One runtime probe per accounting mode, shared by every case below."""
    if os.environ.get(E2E_ENV) != "1":
        pytest.skip(f"{E2E_ENV}=1 not set (the e2e replay lane is opt-in)")
    # INVARIANT: inside the lane the extra is installed, so a missing litellm is a broken lane,
    # never a skip.
    assert find_spec("litellm") is not None, 'the lane must install "screamingface[runtime]"'
    return {
        accounting: _run_probe(tmp_path_factory.mktemp(f"accounting-{accounting}"), accounting)
        for accounting in ACCOUNTING
    }


def test_the_runtime_serves_its_checkout_gateway_on_the_locked_litellm(
    reports: dict[str, Report],
) -> None:
    locked = _locked_version("litellm")
    for report in reports.values():
        assert report["litellm"] == locked
        assert report["source_mode"] == "checkout"
        gateway_source = Path(report["source_root"]) / "apps" / "aigateway" / "src"
        assert Path(report["gateway"]).is_relative_to(gateway_source)
        assert set(report["refused"]) <= METADATA_LOOKUP_HOSTS, "the probe tried to go online"


@pytest.mark.parametrize("accounting", ACCOUNTING)
@pytest.mark.parametrize("provider", PROVIDERS)
def test_one_physical_send_reads_one_attempt(
    reports: dict[str, Report], provider: str, accounting: str
) -> None:
    exchange: Exchange = reports[accounting]["exchanges"][f"{provider}/one"]

    verify_attempts(exchange, 1)
    assert exchange["urls"] == [SEND_URLS[provider]]


@pytest.mark.parametrize("accounting", ACCOUNTING)
@pytest.mark.parametrize("provider", PROVIDERS)
def test_litellm_s_hidden_resend_reads_two_attempts(
    reports: dict[str, Report], provider: str, accounting: str
) -> None:
    exchange: Exchange = reports[accounting]["exchanges"][f"{provider}/resend"]

    verify_attempts(exchange, 2)
    assert exchange["urls"] == [SEND_URLS[provider]] * 2


@pytest.mark.parametrize("accounting", ACCOUNTING)
@pytest.mark.parametrize("provider", PROVIDERS)
def test_an_unobserved_send_is_a_false_zero_the_check_refuses(
    reports: dict[str, Report], provider: str, accounting: str
) -> None:
    exchange: Exchange = reports[accounting]["exchanges"][f"{provider}/unobserved"]

    # The answer was served and the fake transport saw its send, yet the Gateway reported none.
    assert (exchange["status"], exchange["header"]) == (200, "0")
    assert exchange["urls"] == [SEND_URLS[provider]]
    with pytest.raises(AssertionError):
        verify_attempts(exchange, 1)


def _evidence(status: int, header: str | None, seen: int) -> Exchange:
    return {"status": status, "header": header, "urls": [SEND_URLS["ollama"]] * seen, "detail": ""}


@pytest.mark.parametrize(
    ("exchange", "sends"),
    [
        pytest.param(_evidence(200, None, 1), 1, id="header-missing"),
        pytest.param(_evidence(200, "0", 1), 1, id="false-zero"),
        pytest.param(_evidence(200, "1", 2), 2, id="resend-uncounted"),
        pytest.param(_evidence(200, "1", 1), 2, id="no-resend-happened"),
        pytest.param(_evidence(200, "2", 1), 1, id="overcount"),
        pytest.param(_evidence(502, "1", 1), 1, id="not-served"),
    ],
)
def test_the_check_refuses_absent_or_wrong_evidence(exchange: Exchange, sends: int) -> None:
    with pytest.raises(AssertionError):
        verify_attempts(exchange, sends)


def test_the_check_accepts_agreeing_evidence() -> None:
    verify_attempts(_evidence(200, "2", 2), 2)


if __name__ == "__main__":
    _probe(Path(sys.argv[1]))
