from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .board_pages import register_board_pages
from .config import Settings

PUBLIC_ARTIFACTS = (
    "livetruth-latest.jsonl",
    "livetruth-latest.eval.jsonl",
    "livetruth-masking.dataset.jsonl",
)
FORBIDDEN_ARTIFACTS = (
    "livetruth-latest.eval.jsonl.txt",
    "livetruth-latest.answer-key.jsonl",
)
TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"


def register_portal(app: FastAPI, settings: Settings) -> None:
    portal_dir = _resolve_portal_dir(settings)
    artifacts_dir = _resolve_artifacts_dir(settings)
    _validate_public_artifacts(artifacts_dir)

    _register_forbidden_artifacts(app)
    _register_public_artifacts(app, artifacts_dir)
    register_board_pages(app, portal_dir)

    app.mount("/", StaticFiles(directory=portal_dir, html=True), name="portal")


def _app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_portal_dir(settings: Settings) -> Path:
    portal_dir = settings.portal_dir or _app_root() / "portal"
    if not portal_dir.is_dir():
        raise RuntimeError(f"portal directory not found: {portal_dir}")
    return portal_dir


def _resolve_artifacts_dir(settings: Settings) -> Path:
    artifacts_dir = settings.portal_artifacts_dir or _app_root() / "artifacts"
    if not artifacts_dir.is_dir():
        raise RuntimeError(f"portal artifacts directory not found: {artifacts_dir}")
    return artifacts_dir


def _validate_public_artifacts(artifacts_dir: Path) -> None:
    for name in PUBLIC_ARTIFACTS:
        path = artifacts_dir / name
        if not path.is_file():
            raise RuntimeError(f"portal artifact not found: {path}")


def _register_public_artifacts(app: FastAPI, artifacts_dir: Path) -> None:
    for name in PUBLIC_ARTIFACTS:
        app.get(f"/{name}", include_in_schema=False)(_artifact_response(artifacts_dir / name))


def _register_forbidden_artifacts(app: FastAPI) -> None:
    for name in FORBIDDEN_ARTIFACTS:
        app.get(f"/{name}", include_in_schema=False)(_not_found)


def _artifact_response(path: Path) -> Callable[[], FileResponse]:
    def endpoint() -> FileResponse:
        return FileResponse(path, media_type=TEXT_MEDIA_TYPE)

    return endpoint


def _not_found() -> None:
    raise HTTPException(status_code=404)
