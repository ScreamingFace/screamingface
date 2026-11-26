"""The body cap leaves a path that keeps its own cap to that path's route (OME-1970).

FEATURE: Case files by blob reference (OME-1970, PR 4; decision 4) — the upload route takes
files up to 15,000,000 bytes, over the app-wide 12 MiB cap, and refuses larger ones itself.
INVARIANT: only a whole-segment prefix is exempt, and every other path keeps the app-wide cap.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from aigateway.middleware import BodyCapMiddleware


def _app() -> FastAPI:
    app = FastAPI()

    @app.put("/v1/blobs/sha256/{digest}")
    async def upload(digest: str, request: Request) -> dict[str, int]:
        return {"read": len(await request.body())}

    @app.put("/v1/blobsy")
    async def lookalike(request: Request) -> dict[str, int]:
        return {"read": len(await request.body())}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> dict[str, int]:
        return {"read": len(await request.body())}

    app.add_middleware(BodyCapMiddleware, max_bytes=100, exempt_prefixes=("/v1/blobs/",))
    return app


def test_a_body_under_an_exempt_prefix_passes_the_app_wide_cap() -> None:
    client = TestClient(_app())

    resp = client.put("/v1/blobs/sha256/" + "0" * 64, content=b"x" * 500)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"read": 500}


def test_every_other_path_keeps_the_app_wide_cap() -> None:
    client = TestClient(_app())

    assert client.post("/v1/chat/completions", content=b"x" * 500).status_code == 413
    # WHY: `/v1/blobsy` starts with `/v1/blobs` but is not under the `/v1/blobs/` segment.
    assert client.put("/v1/blobsy", content=b"x" * 500).status_code == 413


def test_no_exempt_prefix_is_the_default() -> None:
    app = FastAPI()

    @app.put("/v1/blobs/sha256/{digest}")
    async def upload(digest: str, request: Request) -> dict[str, int]:
        return {"read": len(await request.body())}

    app.add_middleware(BodyCapMiddleware, max_bytes=100)

    resp = TestClient(app).put("/v1/blobs/sha256/" + "0" * 64, content=b"x" * 500)

    assert resp.status_code == 413


def test_a_prefix_that_is_not_a_whole_segment_is_refused() -> None:
    async def app(scope, receive, send) -> None:  # pragma: no cover - never called
        return None

    with pytest.raises(ValueError, match="end with"):
        BodyCapMiddleware(app, max_bytes=100, exempt_prefixes=("/v1/blobs",))
