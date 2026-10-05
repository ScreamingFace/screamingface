"""Liveness and readiness — two probes, deliberately different (OME-944).

INVARIANT: `/healthz` is pure liveness and never touches the database. A liveness probe coupled
to a dependency turns one bad backend into a restart loop across every replica (the aigateway-ui
healthz route documents the same lesson).

`/readyz` is the probe that may fail: a cheap, bounded `SELECT 1` on a reserved connection. A
pod that cannot reach its database leaves the Service instead of answering every submission
with a 503. It checks connectivity only — not schema — so it does not catch the breaking-
migration window described in DEPLOYMENT.md.

WHY a reserved connection, not `default` (OME-1452): on the request pool the probe queues behind
every held connection, so a load spike longer than `PROBE_TIMEOUT_S` would mark the pod unready —
on every replica at once, turning a spike into an outage. `READINESS_CONNECTION` is a pool of one
that no model uses, so the probe measures reachability, never pool occupancy.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from tortoise import connections

from ..db import READINESS_CONNECTION

router = APIRouter()
logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 2.0
"""Below the chart's `readinessProbe.timeoutSeconds` (5), so the app answers 503 itself rather
than leaving the kubelet to time out against a held worker."""


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _database_reachable() -> bool:
    try:
        await asyncio.wait_for(
            connections.get(READINESS_CONNECTION).execute_query("SELECT 1"), timeout=PROBE_TIMEOUT_S
        )
    except Exception as exc:
        # WHY every exception: the only answers are "ready" and "not ready". A refused connect
        # surfaces as a bare OSError and an uninitialised Tortoise as a RuntimeError — neither an
        # ORM error — and a probe that propagates turns a 503 the kubelet understands into a 500.
        # Logged, because an unready pod with no reason behind it is an outage with no first clue.
        logger.warning("readiness probe: database not reachable (%r)", exc)
        return False
    return True


@router.get("/readyz")
async def readyz() -> JSONResponse:
    if await _database_reachable():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not ready"}, status_code=503)
