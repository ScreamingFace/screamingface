"""Exact-base scalar conformance with separate, preinstalled product interpreters."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Generator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from uvicorn import Server

FIXTURES = Path(__file__).resolve().parent
PROVIDER = "byom_" + "a" * 32
MODEL = f"{PROVIDER}/distilbert-sst2"
ACCOUNTS = {name: UUID(int=i) for i, name in enumerate(("allow", "deny", "unconnected"), 1)}
PIN = "9f94a3b04de4138225dc013b8cb2d858f99279ea87eb658b184d127e64b699a7"
TEXT = "  MiXeD café\n🦊 "


def _loopback_only(event: str, args: tuple[object, ...]) -> None:
    if event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple) or address[0] != "127.0.0.1":
            raise RuntimeError("test egress must stay on IPv4 loopback")
    if event == "socket.getaddrinfo" and args[0] != "127.0.0.1":
        raise RuntimeError("test DNS is disabled")


async def _announce_and_serve(server: "Server", ready: Path) -> None:
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(15):
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("fixture server exited before listening")
            await asyncio.sleep(0.01)
    (listener,) = server.servers[0].sockets
    ready.write_text(str(listener.getsockname()[1]))
    await task


async def _reference(root: Path) -> None:
    from bert_reference.server import loopback_server

    def tokenizer(text: str, *, add_special_tokens: bool, truncation: bool) -> Sequence[int]:
        assert add_special_tokens and not truncation
        with root.joinpath("inputs.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(text) + "\n")
        return (101,) + (7,) * (511 if text == "over-token" else 1) + (102,)

    def head(ids: Sequence[int]) -> Sequence[object]:
        assert len(ids) == 3
        return (0.0, 0.0)

    def load(snapshot: Mapping[str, bytes]):
        assert snapshot["model.safetensors"] == b"head"
        return tokenizer, head

    artifact = root / "artifact"
    artifact.mkdir()
    for name, content in {
        "manifest.json": (FIXTURES / "manifest_fixture.json").read_bytes(),
        "config.json": b"{}",
        "tokenizer_config.json": b"{}",
        "model.safetensors": b"head",
        "vocab.txt": b"abc",
    }.items():
        (artifact / name).write_bytes(content)
    settings = {
        "SF_BERT_REFERENCE_ARTIFACT_ROOT": str(artifact),
        "SF_BERT_REFERENCE_MANIFEST_SHA256": PIN,
    }
    await _announce_and_serve(loopback_server(settings, load, port=0), root / "reference.port")


async def _gateway(root: Path, origin: str) -> None:
    from ipaddress import ip_network

    import uvicorn
    from aigateway.config import Settings
    from aigateway.core.auth import middleware
    from aigateway.core.provider_access.types import Authorization, CredentialTarget, TargetMissing
    from aigateway.core.registry import ProviderRegistry
    from aigateway.main import create_app

    async def account_for_identity(identity):
        key = identity.username.removesuffix("@fixture.invalid")
        return SimpleNamespace(id=ACCOUNTS[key]) if key in ACCOUNTS else None

    middleware.account_for_identity = account_for_identity

    class SyntheticAccess:
        async def resolve(self, account_id, provider, selector, *, plugin):
            if account_id != str(ACCOUNTS["allow"]):
                raise TargetMissing(provider, "fixture")
            return CredentialTarget("stored", "api_key", None, "fixture", None)

        def auth_mode(self, target, plugin):
            return "api_key"

        async def authorize(self, target, *, plugin, provider):
            return Authorization({"Authorization": "Bearer synthetic-fixture"}, None, "api_key")

    config = root / "endpoints.toml"
    grants = json.dumps([str(ACCOUNTS[k]) for k in ("allow", "unconnected")])
    config.write_text(
        f'schema_version = 1\n[[endpoints]]\nid = "{PROVIDER}"\ndisplay_name = "Local fixture"\n'
        f'enabled = true\norigin = "{origin}"\nvalidation_target = "distilbert-sst2"\n'
        f"allowed_account_ids = {grants}\n"
        "[[endpoints.targets]]\n"
        + (FIXTURES.parent / "target.toml").read_text()
        + "[endpoints.targets.limits]\nmax_text_chars = 32\nmax_labels = 2\nmax_label_bytes = 8\n"
    )
    app = create_app(
        Settings(
            auth_mode="cloudflare_headers",
            allowed_networks=(ip_network("127.0.0.1/32"),),
            remote_endpoints_config=config,
            discovery_enabled=False,
        )
    )
    app.state.provider_access = SyntheticAccess()
    plugin = app.state.providers.get(PROVIDER)
    # WHY: this fixture exercises one real Remote Endpoint, not ambient local model discovery.
    registry = ProviderRegistry()
    registry.register(plugin)
    app.state.providers = registry
    readiness = await plugin.api_key_validator().validate("synthetic-fixture")
    assert readiness.state.value == "valid"

    async def observed_app(scope, receive, send):
        async def record(event):
            path = scope.get("path")
            if path == "/v1/classifications" and event["type"] == "http.response.start":
                attempts = dict(event["headers"])[b"x-aigw-upstream-attempts"]
                with root.joinpath("gateway.jsonl").open("a", encoding="utf-8") as out:
                    out.write(json.dumps([event["status"], int(attempts)]) + "\n")
            await send(event)

        await app(scope, receive, record)

    server = uvicorn.Server(uvicorn.Config(observed_app, port=0, lifespan="off", access_log=False))
    await _announce_and_serve(server, root / "gateway.port")


async def _engine(root: Path, gateway: str) -> None:
    import uvicorn
    from screamingface_engine.config import Settings
    from screamingface_engine.local import create_local_app

    world = root / "world.toml"
    world.write_text(
        f'[aigateway]\nbase_url = "{gateway}"\ndefault_route = "/anthropic/claude-haiku-4-5"\n'
    )
    env = {**os.environ, "URL4_RUNNER_CONFIG": str(world)}
    app = create_local_app(Settings(aigateway_base_url=gateway), env=env)
    server = uvicorn.Server(uvicorn.Config(app, port=0, access_log=False))
    await _announce_and_serve(server, root / "engine.port")


def _sdk(engine: str) -> None:
    import httpx
    from screamingface import Client
    from screamingface.errors import ScreamingFaceError

    class SyntheticIngress(httpx.HTTPTransport):
        account = "allow"

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            assert str(request.url).startswith(engine + "/")
            request.headers["X-User-Email"] = f"{self.account}@fixture.invalid"
            return super().handle_request(request)

    ingress = SyntheticIngress()
    with Client(engine_url=engine, http_transport=ingress, save_results=False) as client:
        result = client.classify(MODEL, TEXT)
        assert [(row.label, row.score) for row in result.scores] == [
            ("NEGATIVE", 0.5),
            ("POSITIVE", 0.5),
        ]
        for account, text, code in (
            ("deny", "denied input", "classifier_not_found"),
            ("unconnected", "unconnected input", "profile_not_found"),
            ("allow", "K" * 33, "classifier_limit_exceeded"),
            ("allow", "over-token", "provider_error"),
        ):
            ingress.account = account
            try:
                client.classify(MODEL, text)
            except ScreamingFaceError as exc:
                assert exc.code == code, (exc.code, code)
                continue
            raise AssertionError("classified an input that should have been refused")


@contextmanager
def _process(python: str, role: str, root: Path, *args: str) -> Generator[str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(root),
        "DO_NOT_TRACK": "1",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    }
    with subprocess.Popen(
        [python, str(Path(__file__).resolve()), role, str(root), *args], cwd=root, env=env
    ) as child:
        try:
            ready = root / f"{role}.port"
            deadline = time.monotonic() + 30
            while not ready.is_file():
                if child.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"{role} fixture failed to start")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{int(ready.read_text())}"
        finally:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def _run(gateway_python: str, engine_python: str, sdk_python: str) -> None:
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory).resolve()
        reference = stack.enter_context(_process(sys.executable, "reference", root))
        gateway = stack.enter_context(_process(gateway_python, "gateway", root, reference))
        engine = stack.enter_context(_process(engine_python, "engine", root, gateway))
        subprocess.run(
            [sdk_python, str(Path(__file__).resolve()), "sdk", str(root), engine],
            cwd=root,
            env={"PATH": os.environ["PATH"], "HOME": str(root), "DO_NOT_TRACK": "1"},
            check=True,
            timeout=30,
        )
        observed = [json.loads(row) for row in (root / "inputs.jsonl").read_text().splitlines()]
        assert observed == ["ping", TEXT, "over-token"], observed
        attempts = [json.loads(row) for row in (root / "gateway.jsonl").read_text().splitlines()]
        assert attempts == [[200, 1], [400, 0], [404, 0], [400, 0], [502, 1]], attempts
        print("scalar composition: readiness, exact text, authority and refusal passed")


if __name__ == "__main__":
    sys.addaudithook(_loopback_only)
    match sys.argv[1:]:
        case ["reference", root]:
            asyncio.run(_reference(Path(root)))
        case ["gateway", root, origin]:
            asyncio.run(_gateway(Path(root), origin))
        case ["engine", root, gateway]:
            asyncio.run(_engine(Path(root), gateway))
        case ["sdk", _, engine]:
            _sdk(engine)
        case [gateway_python, engine_python, sdk_python]:
            _run(gateway_python, engine_python, sdk_python)
        case _:
            raise SystemExit("usage: compose_scalar.py GATEWAY_PYTHON ENGINE_PYTHON SDK_PYTHON")
