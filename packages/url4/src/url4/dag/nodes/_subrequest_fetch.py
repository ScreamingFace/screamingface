"""A relative sub-request fetch that encodes its wire target only when someone reads it.

FEATURE: in-process dispatch (memory fix 1, OME-1834;
spec ``docs/spec/2026-11-05-url4-inprocess-dispatch.md``).
STORY: as an operator running a 12k-Case benchmark, the aggregate call's ~150 MB context is
handed to the node's own endpoint as it is, not percent-encoded into a URL and parsed back.
"""

from __future__ import annotations

from dataclasses import fields

from url4.io.layer import FetchRequest
from url4.wire.subrequest import SubrequestCall


class SubrequestFetch(FetchRequest):
    """A :class:`FetchRequest` for ``call`` whose ``target`` is :meth:`SubrequestCall.encode`.

    WHY a lazy ``target`` and not a new port method: the structured call rides INSIDE the
    request, so every ``fetch_ex`` pass-through (``BoundedIOLayer``, the engine's fair-share
    gate, any future wrapper) admits and gates it unchanged, and an adapter that does not
    know this type reads ``target`` and gets exactly today's bytes. Only
    ``url4.peer``'s node looks at ``call`` and, for its own endpoint, never reads ``target``.

    INVARIANT (wire compatibility): ``target`` is the codec output, computed once on first
    read, and the request compares and hashes as the plain :class:`FetchRequest` of those
    bytes — so a recorded request is indistinguishable from today's.
    """

    call: SubrequestCall

    def __init__(self, call: SubrequestCall, *, accept: str | None = None) -> None:
        # WHY not super().__init__: it would assign ``target``, the one field left unset
        # so __getattr__ below can supply it on demand. The rest match FetchRequest's
        # defaults for a relative fetch (RelUrlNode's shape).
        for name, value in (
            ("call", call),
            ("relative", True),
            ("kind", "relative"),
            ("accept", accept),
            ("max_bytes", None),
            ("on_chunk", None),
        ):
            object.__setattr__(self, name, value)

    def __getattr__(self, name: str) -> str:
        # Called only when normal lookup fails, so only for ``target`` before its first read.
        if name != "target":
            raise AttributeError(name)
        target = self.call.encode()
        object.__setattr__(self, "target", target)  # frozen dataclass: cache via object
        return target

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FetchRequest):
            return NotImplemented
        return _identity(self) == _identity(other)

    def __hash__(self) -> int:
        return hash(_identity(self))


def _identity(request: FetchRequest) -> tuple[object, ...]:
    """The fields a plain :class:`FetchRequest` compares on (``compare=False`` ones excluded)."""
    return tuple(getattr(request, f.name) for f in fields(FetchRequest) if f.compare)
