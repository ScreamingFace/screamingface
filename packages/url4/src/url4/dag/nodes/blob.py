"""The file-ref node: a content-addressed source resolved through the bytes port.

FEATURE: file refs in url4 sources (epic ``OME-1529``, unit ``OME-1539``; contract =
``OME-1534`` conformance cases C1–C9).
STORY: as an ensemble author I write ``img:src=blob:sha256/<hex>`` (or the ``/blob/…`` /
``url4://<node>/blob/…`` forms) and the node evaluating that level resolves the bytes —
from its own store, or from the named node — and hands them on beside the ref.

INVARIANT: payloads stay ``str`` and refs travel as text (``OME-1534`` point 4). A resolved
ref is a :class:`ResolvedBlob`: the ref exactly as written, carrying the bytes, so a text
consumer sees the ref and the engine connector (``OME-1545``) takes the bytes from it.

AIDEV-NOTE: the engine may import only ``io.layer`` (``test_layering``), so the bytes port
(``url4.io.media``) and the ``OME-1599`` interim allowlist (``blob_peer_allowed``) are
reached duck-typed on ``ctx.io``, exactly as ``BoundedIOLayer`` forwards them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.blob_ref import BlobAddress, address_of, token_address
from url4.core.errors import ErrorCode, ResolutionError
from url4.core.nodes import RelUrl, Url
from url4.dag.semantics.collection import DECLARED_MEDIA_TYPES
from url4.io.layer import FetchRequest, fetch_result

from url4.dag.node import DagNode, ExecutionContext, Payload  # isort: skip
from url4.dag.nodes._shared import FetchedText  # isort: skip


class ResolvedBlob(str):
    """A resolved file ref: the ref text as written, plus the bytes it names.

    It *is* the ref string — joins, ``$name`` substitution and the packed sources all see
    ``blob:sha256/<hex>`` (or the path / URL form) — and :attr:`body`, :attr:`media_type`
    and :attr:`digest` carry the resolved file for a consumer that can attach it.
    """

    body: bytes
    media_type: str | None
    digest: str

    def __new__(cls, ref: str, *, body: bytes, media_type: str | None, digest: str) -> ResolvedBlob:
        text = super().__new__(cls, ref)
        text.body, text.media_type, text.digest = body, media_type, digest
        return text


@dataclass(eq=False)
class BlobRefNode:
    """Resolve one file ref at the evaluating node (C1 path, C2 remote, C3 token)."""

    address: BlobAddress
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    @classmethod
    def relative_path(cls, path: str) -> BlobRefNode:
        """``/blob/sha256/<hex>`` on the current node (C1)."""
        return cls(_required(address_of(RelUrl(path)), path))

    @classmethod
    def token(cls, token: str) -> BlobRefNode:
        """A bare ``blob:<alg>/<id>`` token, from the node's own store (C3)."""
        return cls(token_address(token))

    @classmethod
    def remote(cls, url: str) -> BlobRefNode:
        """``url4://<node>/blob/sha256/<hex>`` on another node (C2)."""
        return cls(_required(address_of(Url(url)), url))

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        address = self.address
        digest = address.digest
        if digest is None:
            # C5: no store holds a ref of another algorithm or a malformed digest; no I/O.
            raise _not_found(address.ref)
        _check_peer(address, ctx)
        remote = address.authority is not None
        request = FetchRequest(
            address.target, relative=not remote, kind="url4" if remote else "relative"
        )
        body, media_type = await _fetch_bytes(ctx, request, own_store=not remote)
        # INVARIANT: a content address that returns other content never resolves.
        if hashlib.sha256(body).hexdigest() != digest:
            raise ResolutionError(
                f"bytes served for {address.ref!r} do not hash to its digest",
                code=ErrorCode.BLOB_DIGEST_MISMATCH,
                permanent=True,
            )
        return ResolvedBlob(address.ref, body=body, media_type=media_type, digest=digest)


def collection_body(payload: Payload) -> Payload:
    """A resolved blob in collection position: its text body, or C8 when it is not text.

    WHY: a collection is parsed from text (§5.3.7). A text blob iterates exactly as the
    same body fetched as text would; a PNG cannot be iterated, so it is
    ``unsupported_content_type`` (C8) rather than its ref read as a one-line body.
    """
    if not isinstance(payload, ResolvedBlob):
        return payload
    media_type = payload.media_type
    if media_type is None or media_type.startswith("text/") or media_type in DECLARED_MEDIA_TYPES:
        try:
            return FetchedText(payload.body.decode("utf-8"), media_type)
        except UnicodeDecodeError:
            pass
    raise ResolutionError(
        f"{str(payload)!r} is {media_type!r}, which a collection cannot iterate",
        code=ErrorCode.UNSUPPORTED_CONTENT_TYPE,
        permanent=True,
    )


def _required(address: BlobAddress | None, ref: str) -> BlobAddress:
    if address is None:
        raise ValueError(f"{ref!r} is not a file ref")
    return address


def _not_found(ref: str) -> ResolutionError:
    return ResolutionError(
        f"this node holds no bytes for {ref!r}", code=ErrorCode.SOURCE_NOT_FOUND, permanent=True
    )


def _check_peer(address: BlobAddress, ctx: ExecutionContext) -> None:
    """The ``OME-1599`` interim rule: a cross-node fetch only to an allowlisted node.

    INVARIANT (fail closed): an io that declares no ``blob_peer_allowed`` allows no peer.
    """
    if address.authority is None:
        return
    allowed = getattr(ctx.io, "blob_peer_allowed", None)
    if allowed is None or not allowed(address.authority):
        raise ResolutionError(
            f"{address.authority!r} is not an allowed node for blob refs ({address.ref!r})",
            code=ErrorCode.BLOB_PEER_NOT_ALLOWED,
            permanent=True,
        )


async def _fetch_bytes(
    ctx: ExecutionContext, request: FetchRequest, *, own_store: bool
) -> tuple[bytes, str | None]:
    """The bytes port, or (an adapter without it) the text body UTF-8 encoded.

    The fallback mirrors ``url4.io.media.fetch_bytes``: such an adapter can only ever give
    text. A node answering ``endpoint_not_found`` for its own store path does not hold the
    bytes, so it reads as ``source_not_found`` (C5); every other failure passes unchanged.
    """
    try:
        fetch = getattr(ctx.io, "fetch_bytes", None)
        if fetch is not None:
            got = await fetch(request)
            return got.body, got.media_type
        result = await fetch_result(ctx.io, request)
        return result.body.encode("utf-8"), result.media_type
    except ResolutionError as exc:
        if own_store and exc.code == ErrorCode.ENDPOINT_NOT_FOUND:
            raise _not_found(request.target) from exc
        raise


__all__ = ["BlobRefNode", "ResolvedBlob", "collection_body"]
