"""Content-addressed file refs: the three surface forms and how each is addressed.

FEATURE: file refs in url4 sources (epic ``OME-1529``, unit ``OME-1539``; contract =
``OME-1534`` conformance cases C1–C9). Three forms name a file by its sha256:

- ``/blob/sha256/<hex>`` — a relative data URI, resolved on the current node (C1);
- ``url4://<authority>/blob/…`` — a blob on another node (C2, §3.5): remote, so in v1 it is
  ``remote_blob_unsupported`` whatever the authority (#1450 spec §2 F1);
- ``<namespace>:<algorithm>/<digest>`` — a bare content identifier (Part B §5.4.4), resolved
  from the evaluating node's own store (C3). Quoted, ``'blob:…'`` is plain text and never
  resolved (C4). v1 supports exactly ``blob:sha256/<64 lowercase hex>``; any other namespace
  or algorithm is ``unsupported_mode`` (owner decision 2026-10-27, design PR 31 review).

The grammar asks :func:`bare_value` to classify a bare token, the renderer asks
:func:`render_blob_ref`, and the DAG lowering asks :func:`address_of` which sources are
file refs and where their bytes live. Pure functions over strings; no I/O here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from url4.core.errors import RenderError
from url4.core.nodes import BlobRef, Node, RelUrl, Text, Url

# INVARIANT: Part B §8 ``content-id``, the whole token, ASCII only, case-sensitive. The
# digest is an opaque key: it excludes ``/``, and ``.``/``..`` are refused (the lookahead), so a
# token can never address a path outside ``/blob/<alg>/``.
_TOKEN_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9-]*):([A-Za-z][A-Za-z0-9-]*)/(?!\.\.?\Z)([A-Za-z0-9_.-]+)", re.ASCII
)
# WHY: the one (namespace, algorithm) v1 supports; anything else is unsupported_mode.
_SUPPORTED = ("blob", "sha256")
_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)  # never case-folded: an opaque key
_HEX = r"[0-9a-fA-F]{64}"
_PATH_RE = re.compile(rf"/blob/sha256/({_HEX})", re.ASCII)
# INVARIANT (fail closed, D1): ANY authority (userinfo, port, empty) and anything after
# ``/blob`` (another algorithm, a query) is a remote blob ref — never a plain web fetch.
_REMOTE_RE = re.compile(r"(?i:url4)://([^/?#]*)/blob(?:[/?#].*)?", re.ASCII | re.DOTALL)


def bare_value(token: str) -> Text | BlobRef:
    """A bare token that is wholly a content identifier is a :class:`BlobRef`; else text."""
    return BlobRef(token) if _TOKEN_RE.fullmatch(token) else Text(token)


def render_blob_ref(node: BlobRef) -> str:
    """The token, unquoted: quoting would turn it into text (C4), so a bad one is refused."""
    if _TOKEN_RE.fullmatch(node.value) is None:
        raise RenderError(f"BlobRef value {node.value!r} is not a content identifier")
    return node.value


@dataclass(frozen=True)
class BlobAddress:
    """Where a file ref's bytes live, as the evaluating node sees it.

    ``digest`` is the lower-case sha256 the bytes must hash to, or ``None`` when no store
    can hold the ref (a ``blob:sha256`` digest that is not 64 lower-case hex digits): such a
    ref is ``source_not_found`` without any I/O (C5). An ``unsupported`` token names a
    namespace or algorithm v1 does not support: ``unsupported_mode``, no I/O. A ``remote``
    ref carries its ``authority`` and no digest: v1 never fetches it (F1).
    """

    ref: str
    form: Literal["path", "token", "unsupported", "remote"]
    digest: str | None
    authority: str | None = None

    @property
    def target(self) -> str:
        """The fetch target on this node's own store (local forms only)."""
        return f"/blob/sha256/{self.digest}"


def address_of(node: Node) -> BlobAddress | None:
    """The file-ref address of a value node, or ``None`` when it is not a file ref.

    INVARIANT: only the exact shapes above. Any other ``RelUrl`` / ``Url`` returns
    ``None`` and lowers exactly as before this unit.
    """
    address = None
    if isinstance(node, BlobRef):
        address = token_address(node.value)
    elif isinstance(node, RelUrl) and (m := _PATH_RE.fullmatch(node.value)):
        address = BlobAddress(node.value, "path", m.group(1).lower())
    elif isinstance(node, Url) and (m := _REMOTE_RE.fullmatch(node.value)):
        address = BlobAddress(node.value, "remote", None, m.group(1))
    return address


def token_address(token: str) -> BlobAddress:
    """The own-store address of a content identifier (C3); no digest if unholdable."""
    m = _TOKEN_RE.fullmatch(token)
    if m is None or (m.group(1), m.group(2)) != _SUPPORTED:
        return BlobAddress(token, "unsupported", None)
    digest = m.group(3)
    return BlobAddress(token, "token", digest if _SHA256_RE.fullmatch(digest) else None)


__all__ = ["BlobAddress", "address_of", "bare_value", "render_blob_ref", "token_address"]
