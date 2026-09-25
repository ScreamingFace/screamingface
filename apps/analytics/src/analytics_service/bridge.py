"""FEATURE: consent-gated Colab continuity and browser-mediated delivery.

Cookies are anonymous preferences, not proof of a person or product authorization.
The browser sends its current shared partition state with every event request.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from importlib.resources import files
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.requests import ClientDisconnect

from analytics_service.contract import InvalidPayload, decode_body
from analytics_service.ingestion import AdmissionRejected, Ingestion
from analytics_service.settings import Settings

CONSENT = "__Secure-sf_bridge_consent"
IDENTITY = "__Secure-sf_bridge_id"
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
Handler = Callable[[Request, Ingestion, Callable[[object], object] | None], Awaitable[JSONResponse]]


def choice(request: Request) -> str:
    value = request.cookies.get(CONSENT, "")
    return value[2:] if value in ("1.accepted", "1.declined") else "unknown"


def identity(request: Request) -> str | None:
    value = request.cookies.get(IDENTITY, "")
    return value if UUID4.fullmatch(value) else None


def cookie(response: Response, name: str, value: str, age: int) -> None:
    # WHY: explicit serialization works on supported Python 3.12/3.13, whose
    # stdlib cookie helpers do not yet accept the Partitioned attribute.
    path = "/bridge" if name == CONSENT else "/bridge/id"
    response.headers.append(
        "set-cookie",
        f"{name}={value}; Path={path}; Max-Age={age}; Secure; HttpOnly; SameSite=None; Partitioned",
    )


def state(request: Request) -> dict[str, str]:
    return {"choice": choice(request), "consent_version": "1"}


def secure(response: Response) -> Response:
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        }
    )
    return response


def failure(status: int, code: str) -> JSONResponse:
    return JSONResponse({"code": code}, status_code=status)


async def control_body(request: Request) -> object:
    if (
        request.headers.get("content-type", "").split(";")[0].strip() != "application/json"
        or request.headers.get("content-encoding", "identity") != "identity"
    ):
        raise AdmissionRejected(415, "unsupported_media_type")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024:
            raise AdmissionRejected(413, "request_too_large")
    return decode_body(bytes(body))


def bind_browser(data: object, browser_id: str) -> object:
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise InvalidPayload("invalid_payload")
    for event in data["events"]:
        # INVARIANT: a stale queued batch cannot silently adopt a newly issued ID.
        if not isinstance(event, dict) or any(
            event.get(key) != value
            for key, value in {
                "origin": "colab",
                "surface": "python_sdk",
                "id_scope": "browser",
                "persistent_id": browser_id,
            }.items()
        ):
            raise InvalidPayload("invalid_browser_scope")
    return data


class Bridge:
    def __init__(self, settings: Settings, ingestion: Ingestion, events: Handler):
        self.settings, self.ingestion, self.events = settings, ingestion, events
        # WHY: opt-out remains available when PostHog delivery is disabled.
        self.controls = Ingestion(
            ingestion.delivery,
            enabled=True,
            max_inflight=settings.max_inflight,
            requests_per_minute=settings.requests_per_minute,
        )

    def check_origin(self, request: Request) -> None:
        if (
            request.headers.get("origin") != self.settings.bridge_origin
            or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
        ):
            raise AdmissionRejected(403, "invalid_origin")

    async def handle(self, request: Request) -> Response:
        admitted = False
        try:
            self.check_origin(request)
            if request.url.path == "/bridge/id/events":
                response = await self.deliver(request)
            else:
                self.controls.enter()
                admitted = True
                async with asyncio.timeout(1.5):
                    data = await control_body(request)
                    response = self.control(request, data)
        except AdmissionRejected as exc:
            response = failure(exc.status, exc.code)
        except InvalidPayload:
            response = failure(422, "invalid_payload")
        except (ValueError, UnicodeDecodeError, RecursionError):
            response = failure(400, "malformed_json")
        except ClientDisconnect:
            response = failure(499, "disconnected")
        except TimeoutError:
            response = failure(503, "unavailable")
        finally:
            if admitted:
                self.controls.leave()
        return secure(response)

    async def deliver(self, request: Request) -> Response:
        browser_id = identity(request)
        if choice(request) != "accepted" or browser_id is None:
            raise AdmissionRejected(403, "consent_required")
        return await self.events(
            request, self.ingestion, lambda data: bind_browser(data, browser_id)
        )

    def control(self, request: Request, data: object) -> Response:
        if request.url.path == "/bridge/consent":
            return self.set_consent(data, choice(request))
        if data != {}:
            raise InvalidPayload("invalid_payload")
        if request.url.path == "/bridge/id/revoke":
            if choice(request) != "declined":
                raise AdmissionRejected(409, "decline_first")
            response = JSONResponse(state(request))
            cookie(response, IDENTITY, "", 0)
            return response
        if choice(request) != "accepted":
            raise AdmissionRejected(403, "consent_required")
        value = identity(request) or str(uuid4())
        response = JSONResponse({**state(request), "persistent_id": value, "id_scope": "browser"})
        cookie(response, IDENTITY, value, self.settings.bridge_cookie_max_age)
        cookie(response, CONSENT, "1.accepted", self.settings.bridge_cookie_max_age)
        return response

    def set_consent(self, data: object, previous: str) -> Response:
        if (
            not isinstance(data, dict)
            or set(data) != {"choice", "consent_version"}
            or data["choice"] not in ("accepted", "declined")
            or data["consent_version"] != "1"
        ):
            raise InvalidPayload("invalid_choice")
        response = JSONResponse(data)
        cookie(response, CONSENT, f"1.{data['choice']}", self.settings.bridge_cookie_max_age)
        if data["choice"] == "declined" or previous != "accepted":
            cookie(response, IDENTITY, "", 0)
        return response


def install_bridge(app: FastAPI, settings: Settings, ingestion: Ingestion, events: Handler) -> None:
    bridge = Bridge(settings, ingestion, events)
    parents = [item.strip() for item in settings.bridge_parent_origins.split(",")]
    ancestors = " ".join(
        sorted(
            set(parents + [item.strip() for item in settings.bridge_ancestor_origins.split(",")])
        )
    )
    script = files("analytics_service").joinpath("bridge.js").read_text()
    script = "const allowedParents = " + json.dumps(parents) + ";\n" + script

    @app.get("/bridge/consent")
    async def page():
        response = HTMLResponse(
            '<!doctype html><meta charset="utf-8"><title>Analytics bridge</title>'
            '<script src="/bridge/script.js"></script>'
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; connect-src 'self'; "
            f"frame-ancestors {ancestors}; base-uri 'none'; form-action 'none'"
        )
        return secure(response)

    @app.get("/bridge/script.js")
    async def javascript():
        return secure(Response(script, media_type="text/javascript"))

    @app.get("/bridge/consent/state")
    async def consent_state(request: Request):
        return secure(JSONResponse(state(request)))

    for path in ("/bridge/consent", "/bridge/id", "/bridge/id/revoke", "/bridge/id/events"):
        app.add_api_route(path, bridge.handle, methods=["POST"], response_model=None)
