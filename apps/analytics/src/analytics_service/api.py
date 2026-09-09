"""Bounded HTTP intake with sanitized errors."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from analytics_service.contract import EventTooLarge, InvalidPayload, decode_body, parse_batch
from analytics_service.ingestion import AdmissionRejected, Ingestion
from analytics_service.ports import DeliveryUnavailable, EventDelivery, UpstreamRejected
from analytics_service.settings import Settings


async def read_body(request: Request) -> bytes:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise AdmissionRejected(415, "unsupported_media_type")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise AdmissionRejected(415, "unsupported_encoding")
    data = bytearray()
    async with asyncio.timeout(2):
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 65536:
                raise AdmissionRejected(413, "request_too_large")
    return bytes(data)


async def disconnected(request: Request) -> None:
    while (await request.receive())["type"] != "http.disconnect":
        await asyncio.sleep(0)


async def forward_connected(request: Request, ingestion: Ingestion, data: object) -> int:
    batch = parse_batch(data)
    send = asyncio.create_task(ingestion.forward(batch))
    watch = asyncio.create_task(disconnected(request))
    try:
        done, _ = await asyncio.wait({send, watch}, return_when=asyncio.FIRST_COMPLETED)
        if watch in done:
            raise ClientDisconnect()
        return await send
    finally:
        # INVARIANT: disconnect/cancellation leaves no orphan delivery or retry tasks.
        send.cancel()
        watch.cancel()
        await asyncio.gather(send, watch, return_exceptions=True)


def error_response(status: int, code: str) -> JSONResponse:
    headers = {"Retry-After": "1"} if status in (429, 503) else {}
    return JSONResponse({"code": code}, status_code=status, headers=headers)


async def receive_events(request: Request, ingestion: Ingestion) -> JSONResponse:
    try:
        data = decode_body(await read_body(request))
        count = await forward_connected(request, ingestion, data)
        response = JSONResponse({"status": "upstream_accepted", "count": count}, status_code=202)
    except EventTooLarge:
        response = error_response(413, "event_too_large")
    except InvalidPayload:
        response = error_response(422, "invalid_payload")
    except (ValueError, UnicodeDecodeError, RecursionError):
        response = error_response(400, "malformed_json")
    except UpstreamRejected:
        response = error_response(502, "upstream_rejected")
    except (DeliveryUnavailable, TimeoutError):
        response = error_response(503, "unavailable")
    return response


def create_app(settings: Settings, delivery: EventDelivery, *, cleanup=None) -> FastAPI:
    ingestion = Ingestion(
        delivery,
        enabled=settings.enabled,
        max_inflight=settings.max_inflight,
        requests_per_minute=settings.requests_per_minute,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            ingestion.draining = True
            if cleanup is not None:
                await cleanup()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ingestion = ingestion

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready():
        return JSONResponse(
            {"ready": ingestion.enabled and not ingestion.draining},
            status_code=200 if ingestion.enabled and not ingestion.draining else 503,
        )

    @app.post("/v1/events")
    async def events(request: Request):
        return await handle_events(request, ingestion)

    return app


async def handle_events(request: Request, ingestion: Ingestion):
    admitted = False
    try:
        ingestion.enter()
        admitted = True
        response = await receive_events(request, ingestion)
    except AdmissionRejected as exc:
        response = error_response(exc.status, exc.code)
    except ClientDisconnect:
        response = error_response(499, "disconnected")
    finally:
        if admitted:
            ingestion.leave()
    ingestion.counters[str(response.status_code)] += 1
    return response
