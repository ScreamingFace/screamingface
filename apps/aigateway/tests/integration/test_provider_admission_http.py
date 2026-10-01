"""Real localhost disconnects and timeout responses; no upstream provider calls."""

import asyncio
import logging
import socket
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request

from aigateway.config import Settings
from aigateway.core.auth.local_only import AuthDisabledLocalOnlyMiddleware
from aigateway.core.concurrency import provider_slot
from aigateway.middleware.call_id import CallIdMiddleware
from aigateway.routes.chat_dispatch import _dispatch_with_backpressure


@asynccontextmanager
async def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", lifespan="off", timeout_graceful_shutdown=1)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                    raise AssertionError("HTTP server exited before startup")
                await asyncio.sleep(0.005)
        yield port
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 5)
        finally:
            sock.close()


def app_for_test(local_only_middleware=False, **settings):
    app = FastAPI()
    app.state.settings = Settings(provider_max_concurrency=1, **settings)
    if local_only_middleware:
        app.add_middleware(AuthDisabledLocalOnlyMiddleware)
    app.add_middleware(CallIdMiddleware)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queue", "execution"])
@pytest.mark.parametrize("local_only_middleware", [False, True])
async def test_socket_disconnect_frees_capacity(phase, local_only_middleware):
    app = app_for_test(local_only_middleware)
    received = asyncio.Event()
    entered = asyncio.Event()
    completed = asyncio.Event()
    calls = []

    async def provider(body):
        calls.append(body)
        entered.set()
        await asyncio.Event().wait()

    @app.post("/")
    async def route(req: Request):
        body = await req.json()
        received.set()
        try:
            return await _dispatch_with_backpressure(
                req, SimpleNamespace(chat_completion=provider), "fake", body
            )
        finally:
            completed.set()

    async with serve(app) as port:
        async with AsyncExitStack() as slots:
            if phase == "queue":
                await slots.enter_async_context(provider_slot(app, "fake", 1))
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                writer.write(
                    b"POST / HTTP/1.1\r\nHost: localhost\r\n"
                    b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"
                )
                await writer.drain()
                await asyncio.wait_for(received.wait(), 5)
                if phase == "execution":
                    await asyncio.wait_for(entered.wait(), 5)
            finally:
                writer.close()
                await writer.wait_closed()
            await asyncio.wait_for(completed.wait(), 5)
            assert len(calls) == (0 if phase == "queue" else 1)
        async with provider_slot(app, "fake", 1, timeout_s=1):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,expected,code",
    [
        ("queue", 503, "provider_queue_timeout"),
        ("execution", 504, "provider_execution_timeout"),
        ("caller", 504, "caller_deadline_exceeded"),
    ],
)
async def test_socket_wire_contract(phase, expected, code):
    app = app_for_test(provider_queue_timeout_s=0.03, provider_execution_timeout_s=0.03)

    async def provider(body):
        await asyncio.Event().wait()

    @app.post("/")
    async def route(req: Request):
        await req.json()
        return await _dispatch_with_backpressure(
            req, SimpleNamespace(chat_completion=provider), "fake", {}
        )

    async with serve(app) as port:
        async with AsyncExitStack() as slots:
            if phase == "queue":
                await slots.enter_async_context(provider_slot(app, "fake", 1))
            headers = {"x-aigw-remaining-timeout-s": ".01"} if phase == "caller" else {}
            async with httpx.AsyncClient() as client:
                r = await client.post(f"http://127.0.0.1:{port}/", json={}, headers=headers)
            assert r.status_code == expected
            assert r.json()["detail"]["code"] == code
            assert r.headers.get("retry-after") == ("1" if phase == "queue" else None)
            assert "x-aigw-trace-id" in r.headers
        async with provider_slot(app, "fake", 1, timeout_s=0.1):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queue", "execution"])
@pytest.mark.parametrize("local_only_middleware", [False, True])
async def test_socket_disconnect_does_not_log_asgi_error(
    phase, local_only_middleware, monkeypatch, caplog
):
    config = uvicorn.Config
    error_logger = logging.getLogger("uvicorn.error")

    def error_level_config(*args, **kwargs):
        kwargs["log_level"] = "error"
        configured = config(*args, **kwargs)
        # WHY: uvicorn configures a non-propagating logger; capture its actual errors.
        error_logger.addHandler(caplog.handler)
        return configured

    monkeypatch.setattr(uvicorn, "Config", error_level_config)
    try:
        with caplog.at_level("INFO", logger="aigateway.core.admission"):
            await test_socket_disconnect_frees_capacity(phase, local_only_middleware)
        assert not any("Exception in ASGI application" in r.getMessage() for r in caplog.records)
        assert any(
            getattr(r, "outcome", None) == "cancelled" and r.levelno == logging.INFO
            for r in caplog.records
        )
    finally:
        error_logger.removeHandler(caplog.handler)
