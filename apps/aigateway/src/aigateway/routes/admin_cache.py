"""Admin routes for the response-cache snapshot upload (OME-952).

Four routes, all behind :class:`CurrentAdmin` and audited by the admin router's
``AdminAuditRoute`` — a cache load mutates state EVERY caller of the gateway shares, so every
attempt (including refusals) is logged with its actor, exactly like the account routes.

Synchronous refusals (4xx before any job exists): malformed multipart fields (422 by FastAPI),
an unknown mode (400), a non-Postgres database (400), an upload already over the size cap
(413), and a load already running (409). Everything else is judged inside the job, because
the honest answer for a 40 MB gzip archive is a ``202`` plus a pollable record, not a request
that blocks for the load's duration.

The upload is spooled to a temp file BEFORE the job starts: a Starlette ``UploadFile`` is
request-scoped, and the job outlives the response. Spooling also fixes the digest — the
sha256 the manifest check compares — and enforces the size cap on ACTUAL bytes, not the
``Content-Length`` a client may understate.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from tortoise import Tortoise
from tortoise.backends.asyncpg.client import AsyncpgDBClient

from ..core.admin_schemas import AdminCacheInfoOut, AdminCacheJobList, AdminCacheJobOut
from ..core.auth.admin import CurrentAdmin
from ..core.request_cache.models import RequestCacheEntry
from ..core.request_cache.revisions import active_cache_revisions
from ..core.request_cache.upload_job import (
    CacheUploadBusy,
    CacheUploadRunner,
    UploadAcceptance,
)
from .admin import AdminAuditRoute

router = APIRouter(prefix="/v1/admin/cache", tags=["Admin"], route_class=AdminAuditRoute)

_SPOOL_CHUNK = 1 << 20
_MANIFEST_CAP = 64 * 1024  # a manifest is a few hundred bytes; 64 KiB is already a lie
_MODES = ("merge", "replace")


def _note_actor(request: Request, admin: CurrentAdmin) -> None:
    request.state.admin_actor = admin.username


def _runner(request: Request) -> CacheUploadRunner:
    return request.app.state.cache_upload_runner


def _postgres_active() -> bool:
    return isinstance(Tortoise.get_connection("default"), AsyncpgDBClient)


async def _spool(upload: UploadFile, destination: Path, cap: int) -> tuple[str, int]:
    """Copy the upload to ``destination`` under ``cap`` bytes; return (sha256 hex, size).

    Reads are chunked: the file never sits in memory whole, and the cap stops a mislabelled
    upload before it fills the disk a temp directory shares with the database.
    """
    digest = hashlib.sha256()
    total = 0
    with destination.open("wb") as sink:
        while chunk := await upload.read(_SPOOL_CHUNK):
            total += len(chunk)
            if total > cap:
                sink.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "cache_upload_too_large",
                        "max_bytes": cap,
                        "message": (
                            f"the upload exceeds the {cap} byte snapshot cap (got at least {total})"
                        ),
                    },
                )
            sink.write(chunk)
            digest.update(chunk)
    return digest.hexdigest(), total


@router.get("/info", response_model=AdminCacheInfoOut)
async def cache_info(request: Request, admin: CurrentAdmin) -> AdminCacheInfoOut:
    _note_actor(request, admin)
    store = request.app.state.request_cache_store
    return AdminCacheInfoOut(
        serving=store.cache_available(),
        row_count=await RequestCacheEntry.all().count(),
        revisions=active_cache_revisions(),
    )


@router.post("/snapshots", status_code=202, response_model=AdminCacheJobOut)
async def upload_snapshot(
    request: Request,
    admin: CurrentAdmin,
    snapshot: UploadFile = File(..., description="gzip'd single-table pg_dump of the cache"),
    manifest: UploadFile | None = File(
        None, description="the .manifest.json snapshot-cache emitted beside the archive"
    ),
    mode: str = Form("merge"),
    force: bool = Form(False),
    acknowledge_loss: bool = Form(False),
) -> AdminCacheJobOut:
    _note_actor(request, admin)
    runner = _runner(request)

    if mode not in _MODES:
        raise HTTPException(
            status_code=400,
            detail={"code": "cache_upload_bad_mode", "mode": mode, "modes": list(_MODES)},
        )
    if not _postgres_active():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "cache_upload_unsupported_database",
                "message": "snapshot loads speak Postgres COPY; this database is not Postgres",
            },
        )

    handle, name = tempfile.mkstemp(prefix="cache-snapshot-", suffix=".sql.gz")
    os.close(handle)
    path = Path(name)
    try:
        sha256_hex, actual_bytes = await _spool(snapshot, path, runner.max_upload_bytes)
        manifest_raw = await manifest.read(_MANIFEST_CAP + 1) if manifest is not None else None
        if manifest_raw is not None and len(manifest_raw) > _MANIFEST_CAP:
            raise HTTPException(
                status_code=413,
                detail={"code": "cache_manifest_too_large", "max_bytes": _MANIFEST_CAP},
            )
        try:
            record = runner.start(
                UploadAcceptance(
                    upload_path=path,
                    sha256_hex=sha256_hex,
                    actual_bytes=actual_bytes,
                    manifest_raw=manifest_raw,
                    mode=mode,  # type: ignore[arg-type]  # checked against _MODES above
                    force=force,
                    acknowledge_loss=acknowledge_loss,
                    actor=admin.username,
                )
            )
        except CacheUploadBusy as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "cache_load_in_progress",
                    "message": "one snapshot load runs at a time; poll the running job",
                },
            ) from exc
    except HTTPException:
        # The spooled file is the job's to delete once accepted; on any synchronous refusal
        # it is ours, and it must not linger in /tmp.
        path.unlink(missing_ok=True)
        raise
    return AdminCacheJobOut.model_validate(record, from_attributes=True)


@router.get("/snapshots/jobs", response_model=AdminCacheJobList)
async def list_cache_jobs(request: Request, admin: CurrentAdmin) -> AdminCacheJobList:
    _note_actor(request, admin)
    return AdminCacheJobList(
        jobs=[
            AdminCacheJobOut.model_validate(job, from_attributes=True)
            for job in _runner(request).jobs()
        ]
    )


@router.get("/snapshots/jobs/{job_id}", response_model=AdminCacheJobOut)
async def get_cache_job(request: Request, admin: CurrentAdmin, job_id: UUID) -> AdminCacheJobOut:
    _note_actor(request, admin)
    job = _runner(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "cache_job_not_found"})
    return AdminCacheJobOut.model_validate(job, from_attributes=True)
