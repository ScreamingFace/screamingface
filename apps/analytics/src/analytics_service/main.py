"""Deployment wiring, separate from core ingestion."""

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import ValidationError

from analytics_service.adapters.posthog import PostHogDelivery
from analytics_service.api import create_app
from analytics_service.settings import Settings


def build_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    client = httpx.AsyncClient(
        trust_env=False,
        limits=httpx.Limits(
            max_connections=config.max_inflight, max_keepalive_connections=config.max_inflight
        ),
    )
    delivery = PostHogDelivery(
        client, config.posthog_host, config.posthog_project_token.get_secret_value()
    )
    return create_app(config, delivery, cleanup=client.aclose)


def main() -> None:
    try:
        config = Settings()
    except ValidationError:
        # WHY: formatted validation errors include input values, possibly secrets.
        raise SystemExit("Invalid analytics configuration") from None
    uvicorn.run(
        build_app(config),
        host=config.host,
        port=config.port,
        access_log=False,
        proxy_headers=False,
        timeout_graceful_shutdown=3,
    )
