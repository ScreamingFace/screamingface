"""Exception hierarchy for the url4 core library.

This module is a dependency-free sink: every other module may import it, and it
imports nothing internal. Keeping it isolated prevents import cycles.

The hierarchy mirrors the phases of evaluation so callers can catch broadly
(:class:`Url4Error`) or narrowly (a specific failure mode):

- :class:`ParseError`     — the expression text is not valid url4 (grammar).
- :class:`ScopeError`     — a ``$name`` / ``$N`` reference is unbound (context).
- :class:`ResolutionError`— a source could not be resolved (I/O layer).
- :class:`CollectionError`— a ``*`` collection source is not iterable.
- :class:`CycleError`     — a hand-built node graph contains a dependency cycle.

Every error additionally carries the spec's wire-level vocabulary: ``code`` is
the error-code string a node reports (e.g. ``malformed_source``, spec Part B/C)
and ``permanent`` marks whether retrying can ever succeed (permanent errors
MUST NOT be retried). Subclasses set class-level defaults; both can be
overridden per instance for spec codes that share a Python type — e.g.
``unknown_identity`` or ``expansion_not_iterable`` raised as a
:class:`ResolutionError`/:class:`CollectionError` with an explicit ``code``.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Central vocabulary of the spec's wire-level error codes.

    Each member's value is the exact string the spec assigns and that appears
    on the wire, so code never changes even when a member is renamed. Members
    are ``str`` (``StrEnum``), so ``exc.code == "malformed_source"`` and
    f-string rendering keep working.
    """

    INTERNAL_ERROR = "internal_error"
    MALFORMED_SOURCE = "malformed_source"
    UNBOUND_REFERENCE = "unbound_reference"
    RESOLUTION_FAILED = "resolution_failed"
    CYCLE_DETECTED = "cycle_detected"
    UNRENDERABLE = "unrenderable"
    MISSING_INTENT = "missing_intent"
    UNKNOWN_IDENTITY = "unknown_identity"
    ENDPOINT_NOT_FOUND = "endpoint_not_found"
    TIMEOUT = "timeout"
    ADMISSION_TIMEOUT = "x.admission_timeout"
    """A guarded source's ``;t=`` ran out while it still waited for the run-wide I/O
    permit: no request was sent. Transient, like ``timeout``, but it names the run's own
    concurrency cap as the cause, not the source. An implementation code, so it carries
    the ``x.`` prefix the spec reserves for them (Spec C §13.5.2)."""
    SOURCE_DESTINATION_BLOCKED = "x.source_destination_blocked"
    """The url4 HTTP source guard refused a hop: a disallowed scheme, an address in a refused
    range (after DNS, on any redirect hop), an ``https``→``http`` downgrade, or a ``url4://``
    peer off the operator's allowlist. Permanent (spec F1b, OME-1544)."""
    SOURCE_REDIRECT_LIMIT = "x.source_redirect_limit"
    """A source fetch exceeded the guard's redirect-hop limit (default 3). Permanent."""
    SOURCE_TOO_LARGE = "x.source_too_large"
    """A source body passed the guard's streaming cap on decoded bytes; the read was aborted
    mid-stream. Permanent."""
    SOURCE_TIMEOUT = "x.source_timeout"
    """A source fetch hit the connect timeout or the one total deadline across all hops.
    Transient, like ``timeout``."""
    EXPANSION_NOT_ITERABLE = "expansion_not_iterable"
    QUORUM_NOT_MET = "quorum_not_met"
    UNKNOWN_PROCESSOR = "unknown_processor"
    SELF_REF_ON_NON_URL4 = "self_ref_on_non_url4"
    IDENTITY_REF_ON_NON_URL4 = "identity_ref_on_non_url4"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    IDENTITY_ACCESS_DENIED = "identity_access_denied"
    CONSENT_REQUIRED = "consent_required"
    CONSENT_WITHHELD = "consent_withheld"
    INTENT_ERROR = "intent_error"
    UNSUPPORTED_MODE = "unsupported_mode"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    """A resolved source has a media type this consumer cannot handle (Spec C §13.5.2,
    conformance case C8) — e.g. a PNG asked for as text. Permanent: the same bytes come back."""
    SOURCE_NOT_FOUND = "source_not_found"
    """The source names content its node does not hold (Spec C §13.2.5, conformance case
    C5) — e.g. a ``blob:sha256/<hex>`` absent from the store. Permanent."""
    BLOB_PEER_NOT_ALLOWED = "x.blob_peer_not_allowed"
    """A ``url4://<node>/blob/…`` ref names a node the run's io does not allowlist: the
    ``OME-1599`` interim rule, until blob refs carry trust checks. Permanent, no I/O."""
    BLOB_DIGEST_MISMATCH = "x.blob_digest_mismatch"
    """The bytes served for a content address do not hash to it. Permanent: a content
    address that returns other content is refused, never passed on."""
    DIRECT_EVAL_REFUSED = "direct_eval_refused"
    """A direct call (one handler, `url4.peer.dispatch_direct`) targeted the eval path, which
    evaluates an expression — the one thing a direct call must never do."""


class Url4Error(Exception):
    """Base class for every error raised by the url4 library."""

    code: str = ErrorCode.INTERNAL_ERROR
    permanent: bool = True

    def __init__(
        self, message: str, *, code: str | None = None, permanent: bool | None = None
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if permanent is not None:
            self.permanent = permanent


class ParseError(Url4Error):
    """The expression could not be parsed into an AST.

    ``position`` is the 0-based character offset into the source expression at
    which parsing failed, or ``None`` when the underlying parser did not report
    one.
    """

    code = ErrorCode.MALFORMED_SOURCE

    def __init__(
        self,
        message: str,
        *,
        position: int | None = None,
        code: str | None = None,
        permanent: bool | None = None,
    ) -> None:
        super().__init__(message, code=code, permanent=permanent)
        self.position = position


class ScopeError(Url4Error):
    """A ``$name`` or ``$N`` variable reference could not be resolved in scope."""

    code = ErrorCode.UNBOUND_REFERENCE


class ResolutionError(Url4Error):
    """A source (URL, relative path, or sub-request) failed to resolve.

    Transient by default — an I/O failure may succeed on retry. Permanent
    resolution outcomes (``unknown_identity``, ``identity_access_denied``, …)
    are raised with explicit ``code=…, permanent=True``.
    """

    code = ErrorCode.RESOLUTION_FAILED
    permanent = False
    retry_after: float | None = None
    """Seconds the source asked the caller to wait before a retry (a ``Retry-After``),
    or ``None``. A retrying guard waits at least this long (Spec C §14.3)."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        permanent: bool | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, code=code, permanent=permanent)
        if retry_after is not None:
            self.retry_after = retry_after


class CollectionError(Url4Error):
    """A ``*`` collection source did not resolve to a usable, iterable value."""

    code = ErrorCode.MALFORMED_SOURCE


class CycleError(Url4Error):
    """A node graph contains a dependency cycle and cannot be executed.

    Compiler-emitted graphs are acyclic by construction; this guards graphs
    assembled by hand from custom nodes.
    """

    code = ErrorCode.CYCLE_DETECTED


class RenderError(Url4Error):
    """An AST node cannot be rendered as url4 text that reparses to itself.

    Raised by :func:`url4.core.render.render` for values the grammar cannot carry
    (a bare URI with unbalanced parens or depth-0 separators, a negative
    weight, over-deep structured annotations) and for node shapes whose
    rendered form would reparse differently (spec §8.1.2 boundary hazards,
    a nested reduce-over-iteration).
    """

    code = ErrorCode.UNRENDERABLE


__all__ = [
    "CollectionError",
    "CycleError",
    "ErrorCode",
    "ParseError",
    "RenderError",
    "ResolutionError",
    "ScopeError",
    "Url4Error",
]
