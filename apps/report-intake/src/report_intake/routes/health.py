"""Liveness. Static, and it stays that way.

INVARIANT: this module never grows a storage import, a settings read, or a dependency of any
kind. `/healthz` is the answer to "is this process alive", and a liveness probe that depends on
the database turns one bad database into a cluster-wide restart loop — every replica fails its
kubelet probe at once and none of them can come back, because the thing they are waiting for is
the thing they are being killed for. `/readyz` is the probe that may fail closed.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
