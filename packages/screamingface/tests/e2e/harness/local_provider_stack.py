"""Zero-egress full stack for OME-1499 local-provider execution."""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from ._local_proc import ManagedProcess, clean_env, free_port, repo_root, sync_project, venv_bin


class _LocalModelServer:
    def __init__(self, canonical_ids: tuple[str, ...]) -> None:
        self._upstream_ids = tuple(model.removeprefix("local/") for model in canonical_ids)
        self._seen: list[str] = []
        self._refusals: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        if self._server is not None:
            raise RuntimeError("local model server is already started")
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server, self._thread = server, thread
        host, port = server.server_address[:2]
        return f"http://{host}:{port}"

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=10)

    @property
    def seen(self) -> tuple[str, ...]:
        return tuple(f"local/{model}" for model in self._seen)

    @property
    def refusals(self) -> tuple[str, ...]:
        return tuple(self._refusals)


class _Handler(BaseHTTPRequestHandler):
    server_state: _LocalModelServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/v1/models":
            self.server_state._refusals.append(self.path)  # noqa: SLF001
            self._reply(404, {"error": "unroutable"})
            return
        self._reply(
            200,
            {
                "object": "list",
                "data": [
                    {"id": model, "object": "model"}
                    for model in self.server_state._upstream_ids  # noqa: SLF001
                ],
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/v1/chat/completions":
            self.server_state._refusals.append(self.path)  # noqa: SLF001
            self._reply(404, {"error": "unroutable"})
            return
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        model = body.get("model")
        if model not in self.server_state._upstream_ids:  # noqa: SLF001
            self.server_state._refusals.append(str(model))  # noqa: SLF001
            self._reply(404, {"error": "unknown_model"})
            return
        self.server_state._seen.append(model)  # noqa: SLF001
        self._reply(
            200,
            {
                "id": "chatcmpl-local-e2e",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "B"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _reply(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _handler_for(state: _LocalModelServer) -> type[_Handler]:
    class BoundHandler(_Handler):
        server_state = state

    return BoundHandler


class LocalProviderBackend:
    def __init__(self, *, work_dir: Path, model_ids: tuple[str, ...]) -> None:
        self._work_dir = work_dir
        self._models = _LocalModelServer(model_ids)
        self._gateway: ManagedProcess | None = None

    async def start(self) -> str:
        return await asyncio.to_thread(self._start)

    async def stop(self) -> None:
        await asyncio.to_thread(self._stop)

    @property
    def seen_models(self) -> tuple[str, ...]:
        return self._models.seen

    @property
    def refusals(self) -> tuple[str, ...]:
        return self._models.refusals

    def _start(self) -> str:
        model_url = self._models.start()
        try:
            gateway_dir = repo_root() / "apps" / "aigateway"
            sync_project(gateway_dir)
            database_url = f"sqlite://{self._work_dir / 'aigateway.sqlite3'}"
            env = clean_env(
                {
                    "AIGATEWAY_DATABASE_URL": database_url,
                    "AIGW_AUTH_MODE": "disabled",
                    "AIGW_DISCOVERY_ENABLED": "true",
                    "AIGW_LOCAL_ENABLED": "true",
                    "AIGW_LOCAL_BASE_URL": f"{model_url}/v1",
                }
            )
            subprocess.run(
                [
                    str(venv_bin(gateway_dir, "python")),
                    "-m",
                    "tortoise",
                    "-c",
                    "aigateway.db.TORTOISE_CONFIG",
                    "migrate",
                ],
                cwd=gateway_dir,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            port = free_port()
            self._gateway = ManagedProcess(
                name="aigateway-local-provider",
                command=[
                    str(venv_bin(gateway_dir, "uvicorn")),
                    "aigateway.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                cwd=gateway_dir,
                log_path=self._work_dir / "aigateway-local.log",
            )
            url = f"http://127.0.0.1:{port}"
            self._gateway.start(f"{url}/healthz")
            return url
        except Exception:
            self._stop()
            raise

    def _stop(self) -> None:
        if self._gateway is not None:
            self._gateway.stop()
            self._gateway = None
        self._models.stop()


def prepare_medxpert_assets(root: Path) -> Path:
    engine_dir = repo_root() / "apps" / "screamingface-engine"
    sync_project(engine_dir)
    code = (
        "import sys; from pathlib import Path; "
        "from screamingface_engine.benchmarks.medxpert.prepare import emit; "
        "emit([{'id':'Text-0','question':'Pick B','options':{'A':'alpha','B':'beta'},"
        "'label':'B'}], Path(sys.argv[1])/'medxpert')"
    )
    subprocess.run(
        [str(venv_bin(engine_dir, "python")), "-c", code, str(root)],
        cwd=engine_dir,
        env=clean_env({}),
        check=True,
        capture_output=True,
        text=True,
    )
    return root


__all__ = ["LocalProviderBackend", "prepare_medxpert_assets"]
