from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from tortoise import Tortoise

DEFAULT_DATABASE_URL = "sqlite://./aigateway.sqlite3"


def _default_database_url() -> str:
    return os.environ.get("AIGATEWAY_DATABASE_URL", DEFAULT_DATABASE_URL)


TORTOISE_CONFIG: dict[str, Any] = {
    "connections": {"default": _default_database_url()},
    "apps": {
        "models": {
            "models": [
                "aigateway.core.auth.models",
                "aigateway.core.credential_blob",
                "aigateway.core.oauth.models",
                "aigateway.core.provider_access.models",
                "aigateway.core.request_cache.models",
                "aigateway.core.secrets.models",
            ],
            "default_connection": "default",
            "migrations": "aigateway.migrations",
        }
    },
}


def build_tortoise_config(database_url: str) -> dict[str, Any]:
    config = deepcopy(TORTOISE_CONFIG)
    config["connections"]["default"] = database_url
    return config


async def init_db(database_url: str) -> None:
    await Tortoise.init(config=build_tortoise_config(database_url), _enable_global_fallback=True)


async def close_db() -> None:
    await Tortoise.close_connections()
