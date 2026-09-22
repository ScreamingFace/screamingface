"""Redemption of result claim tickets: serve a spilled result whole, as often as asked.

FEATURE: deliver large results in full instead of cutting them off at 1 MiB (OME-892).

The Runner parks an over-threshold result under its content address and the terminal
result frame carries only `{artifact_id, size_bytes, sha256}`; this route is where a
client trades that ticket for the complete bytes.

WHY two response types (OME-929): the reader port answers with `LocalFile` or
`RemoteStream`, because the two backing stores genuinely differ. A file on our own disk is
served with `FileResponse` — bounded memory AND HTTP Range for resume. Object storage has no
path to hand over, so it is streamed with an explicit `Content-Length` and no Range support,
rather than pretending to a capability it does not have.

INVARIANT: fetching NEVER deletes. Content addressing means one file can back many claim
tickets (identical results dedupe onto one path), a dropped connection must be retryable,
and a Range request must leave the rest of the file fetchable — delete-on-first-GET broke
all three (review finding on OME-892). Artifacts die by TTL alone: the periodic sweeper in
`app.py` is the single cleanup mechanism.
"""

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from screamingface_engine.artifacts import LocalFile
from screamingface_engine.artifacts.signing import (
    EXPIRY_PARAM,
    SIGNATURE_PARAM,
    verify_artifact_signature,
)
from screamingface_engine.auth.dependencies import verified_claims
from screamingface_engine.auth.problem import ProblemException

router = APIRouter()


def _authorize_artifact(request: Request) -> None:
    """Accept a capability token OR a valid unexpired signed URL (OQ-3.2, contracts.md C6).

    FEATURE: the sync caller D9 redirects here holds no capability token, so the spill path
    issues a short-lived signature over the artifact id and its expiry. This route verifies it
    as an ALTERNATIVE credential.

    INVARIANT: the bare route is NOT loosened. A request offering no signature of any kind falls
    straight through to `verified_claims` — the same check, and the same 401, as before this
    unit. An invalid or expired signature ALSO falls through, so with no valid token it is
    refused exactly as a bad token is today.
    """
    settings = request.app.state.settings
    artifact_id = str(request.path_params.get("artifact_id", ""))
    exp = request.query_params.get(EXPIRY_PARAM)
    sig = request.query_params.get(SIGNATURE_PARAM)
    if exp is not None and sig is not None:
        clock = getattr(request.app.state, "clock", None)
        now = clock().timestamp() if clock is not None else time.time()
        if verify_artifact_signature(
            artifact_id,
            exp=exp,
            sig=sig,
            key=settings.artifact_signing_key,
            now=now,
        ):
            return
    verified_claims(request)


# A dependency that authorizes EITHER credential; injected so the failure path is the same
# uniform 401 problem the token path already produces.
ArtifactAccess = Annotated[None, Depends(_authorize_artifact)]


@router.get(
    "/artifacts/{artifact_id}",
    tags=["Runs"],
    summary="Fetch one complete spilled result by its claim ticket",
    # WHY both (OME-929): the handler now returns one of TWO response classes, and FastAPI
    # tries to build a Pydantic response field from the return annotation — which a union of
    # Starlette responses is not. `response_model=None` disables that inference; declaring
    # `response_class` keeps the OpenAPI document stating `application/octet-stream` rather
    # than degrading to an untyped body, which the docs gate would notice.
    response_model=None,
    response_class=Response,
)
async def get_artifact(
    request: Request,
    _access: ArtifactAccess,
    artifact_id: Annotated[
        str, Path(description="Content address from the result frame's artifact reference.")
    ],
) -> Response:
    # WHY direct attribute access, no getattr fallback: `create_app` always builds the
    # store, so its absence is a wiring bug that must fail loudly, not read as a 404.
    store = request.app.state.artifact_store
    # INVARIANT: `content` resolves only lowercase-sha256 ids inside the store — a
    # traversal id and an unknown id are the same 404, never content outside the store.
    #
    # WHY `to_thread`: the port is sync (see `artifacts.ports`), and for object storage this
    # call makes a blocking round trip to learn the object's existence and length. Running it
    # on the loop would stall every other request and the WS heartbeats for its duration.
    content = await asyncio.to_thread(store.content, artifact_id)
    if content is None:
        raise ProblemException(
            status=404,
            title="Unknown artifact",
            detail=f"no artifact is stored under {artifact_id!r} — it may have expired "
            "(artifacts are TTL-swept), or the Runner that produced it wrote to storage "
            "this App cannot read (check the artifact storage settings agree on both sides)",
        )
    if isinstance(content, LocalFile):
        return FileResponse(content.path, media_type="application/octet-stream")
    # INVARIANT: `Content-Length` is set from the ticket's own size, so a truncated upstream
    # body is a protocol error the client detects — not a short response that looks complete.
    # The SDK independently re-verifies size AND sha256 before decoding.
    return StreamingResponse(
        content.stream,
        media_type="application/octet-stream",
        headers={"content-length": str(content.size_bytes)},
    )


__all__ = ["router"]
