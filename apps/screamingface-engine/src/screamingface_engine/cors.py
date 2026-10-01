"""CORS for the Engine's REST surface (spec: docs/spec/2026-09-29-engine-cors-studio.md).

FEATURE (OME-1308, E18 · A local app): the Studio webview calls the Engine cross-origin.
STORY: as a Studio user, I see real runs in the app instead of mock data.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def install_cors(app: FastAPI, origins: Sequence[str]) -> None:
    """Grant CORS to exactly `origins`; an empty sequence grants no origin."""
    # WHY credentials off: Engine auth is header-borne (`Authorization` + the secondary
    # credential header), never cookies, so a credentials grant would only widen what a granted
    # origin can do. Wildcard methods/headers are safe without it and carry `Authorization`.
    #
    # AIDEV-NOTE: CORS does not apply to WebSocket upgrades; the WS surface is unaffected.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
