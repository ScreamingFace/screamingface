"""The file-ref node: a content-addressed source resolved through the bytes port.

FEATURE: file refs in url4 sources (epic ``OME-1529``, unit ``OME-1539``; contract =
``OME-1534`` conformance cases C1–C9, as amended by #1450 spec §2 F1/F2).
STORY: as an ensemble author I write ``img:src=blob:sha256/<hex>`` (or ``/blob/sha256/<hex>``)
and the node evaluating that level resolves the bytes from its own store, verifies them
against the digest, and yields a typed :class:`~url4.dag.attachment.Attachment`.

INVARIANT (D1 / F1): every ``url4://<authority>/blob/…`` ref is remote in v1 and fails
``remote_blob_unsupported``, permanent, BEFORE any I/O — whatever the authority.
INVARIANT (D2 / F2): ``resolve`` returns the ref text as a plain ``str``; the file travels
only as an :class:`Attachment` (:meth:`BlobRefNode.attachment`), never on a ``str``.

AIDEV-NOTE: ``OME-1543`` collects the run's ordered ``attachments[]`` from these nodes
(structure, not strings) before execution and wires them into model calls; until then
``resolve`` verifies the file (so C1/C3/C5 and a digest mismatch fail the run where they
should) and hands on only the ref text. The engine may import only ``io.layer``
(``test_layering``), so the bytes port is reached duck-typed on ``ctx.io``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.blob_ref import BlobAddress, address_of, token_address
from url4.core.errors import ErrorCode, ResolutionError
from url4.core.nodes import RelUrl, Url
from url4.dag.attachment import OCTET_STREAM, Attachment
from url4.dag.attachments import CachedBlob, current_run_files
from url4.dag.semantics.collection import DECLARED_MEDIA_TYPES
from url4.io.layer import FetchRequest, fetch_result

from url4.dag.node import DagNode, ExecutionContext, Payload  # isort: skip
from url4.dag.nodes._shared import FetchedText  # isort: skip


@dataclass(eq=False)
class BlobRefNode:
    """Resolve one file ref at the evaluating node (C1 path, C3 token; C2 refused).

    ``collection`` is set at lowering when the ref sits in collection position (``src*(…)``,
    ``*src=``): then the blob is read as text and is not an attachment (D4), or is C8.
    """

    address: BlobAddress
    collection: bool = False
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    @classmethod
    def relative_path(cls, path: str) -> BlobRefNode:
        """``/blob/sha256/<hex>`` on the current node (C1)."""
        return cls(_required(address_of(RelUrl(path)), path))

    @classmethod
    def token(cls, token: str) -> BlobRefNode:
        """A bare content identifier, from the node's own store (C3)."""
        return cls(token_address(token))

    @classmethod
    def remote(cls, url: str) -> BlobRefNode:
        """``url4://<authority>/blob/…`` (C2): it only ever refuses, in v1."""
        return cls(_required(address_of(Url(url)), url))

    async def attachment(self, ctx: ExecutionContext) -> Attachment:
        """The verified file this ref names, as the typed F2 attachment."""
        body, media_type = await self.verified(ctx)
        return Attachment(
            digest=f"sha256:{self.address.digest}",
            media_type=media_type or OCTET_STREAM,
            body=body,
        )

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        body, media_type = await self.verified(ctx)
        if self.collection:
            return _collection_text(self.address.ref, body, media_type)
        return str(self.address.ref)

    async def verified(self, ctx: ExecutionContext) -> tuple[bytes, str | None]:
        """The bytes and reported media type, sha256-verified; from the run cache on a hit.

        INVARIANT (plan §2.8): inside a ``run()`` the run-start resolver already fetched and
        verified every file the AST names, so a node reads the cache and never fetches again,
        whatever the fan-out width, row count or retries. A miss (a ref only a row template
        names after substitution, or a node evaluated outside ``run()``) fetches as before.
        """
        address = self.address
        if address.form == "remote":
            # D1 / F1: checked first, so no store lookup, DNS or connection is ever attempted.
            raise ResolutionError(
                f"remote blob refs are not supported in v1 ({address.ref!r})",
                code=ErrorCode.REMOTE_BLOB_UNSUPPORTED,
                permanent=True,
            )
        if address.form == "unsupported":
            # Part B §5.4.4 rule 4: a namespace/algorithm v1 does not support. Never text,
            # never source_not_found (that would read as missing bytes); no I/O.
            raise ResolutionError(
                f"content identifier {address.ref!r} names an unsupported namespace or algorithm",
                code=ErrorCode.UNSUPPORTED_MODE,
                permanent=True,
            )
        digest = address.digest
        if digest is None:
            # C5: no store holds a malformed sha256 digest; no I/O.
            raise _not_found(address.ref)
        files = current_run_files()
        cached = None if files is None else files.cache.get(f"sha256:{digest}")
        if isinstance(cached, CachedBlob):
            return cached.body, cached.media_type
        body, media_type = await _fetch_bytes(
            ctx, FetchRequest(address.target, relative=True, kind="relative")
        )
        # INVARIANT: a content address that returns other content never resolves.
        if hashlib.sha256(body).hexdigest() != digest:
            raise ResolutionError(
                f"bytes served for {address.ref!r} do not hash to its digest",
                code=ErrorCode.BLOB_DIGEST_MISMATCH,
                permanent=True,
            )
        return body, media_type


def as_collection(node: DagNode) -> DagNode:
    """Mark a file ref lowered into collection position (D4); any other node is unchanged.

    WHY at lowering: the position is structure the AST knows; deciding it from the payload
    would mean scanning strings (F2).
    """
    if isinstance(node, BlobRefNode):
        node.collection = True
    return node


def _collection_text(ref: str, body: bytes, media_type: str | None) -> FetchedText:
    """A blob in collection position: its text body (D4), or C8 when it is not text.

    WHY: a collection is parsed from text (§5.3.7). A text blob iterates exactly as the
    same body fetched as text would; a PNG cannot be iterated, so it is
    ``unsupported_content_type`` (C8) rather than its ref read as a one-line body.
    """
    if media_type is None or media_type.startswith("text/") or media_type in DECLARED_MEDIA_TYPES:
        try:
            return FetchedText(body.decode("utf-8"), media_type)
        except UnicodeDecodeError:
            pass
    raise ResolutionError(
        f"{ref!r} is {media_type!r}, which a collection cannot iterate",
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


async def _fetch_bytes(ctx: ExecutionContext, request: FetchRequest) -> tuple[bytes, str | None]:
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
        if exc.code == ErrorCode.ENDPOINT_NOT_FOUND:
            raise _not_found(request.target) from exc
        raise


__all__ = ["BlobRefNode", "as_collection"]
