"""Value types and typed refusals of the provider-access port (OME-1200, spec §3.2).

# FEATURE: OME-1138 adapter-first convergence — routes stop reading Profile/Connection rows and
# ask ONE port for a credential target instead.
# INVARIANT: nothing here names an HTTP status or a wire code. A refusal is a typed OUTCOME of
# the read interface; the ONE table that turns it into a response lives at the HTTP edge
# (`routes/provider_access_http.py`). Implementations raise these and never choose codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from ..auth_types import AuthType

if TYPE_CHECKING:
    from .pair_authority import PairAuthority


class ResolvePolicy(Enum):
    """How `resolve` treats a caller with NO stored target at all.

    DISPATCH is chat: no target is a refusal. DATASHEET is the model-parameter contract
    (OME-1167): the DEFAULT selector may answer without a credential — the document is a
    lookup, not a credentialed action. A NAMED selector without a target refuses under both.
    """

    DISPATCH = "dispatch"
    DATASHEET = "datasheet"


# `stored`: a Connection row backs the target and `credential_name` is set.
# `ambient`: no stored row, but the provider names a runtime credential of its own
#            (`plugin.profileless_auth_mode()` is not None — Gemini's ADC path).
# `none`: no stored row and no ambient credential — either the provider needs none
#         (chatless providers such as Ollama) or the DATASHEET policy admitted the absence.
TargetKind = Literal["stored", "ambient", "none"]


@dataclass(frozen=True)
class CredentialTarget:
    """What `resolve` answers: everything a route needs, nothing a route may mutate.

    `context_stamp` is the opaque, non-secret digest input the contract endpoint folds into
    its ids (today's `_context_identity` string, byte for byte). `_backing` is the
    implementation's private handle to the row it resolved — excluded from equality and repr
    so no consumer can depend on its shape.

    # WHY: `_backing` is what lets `authorize` and `record_dispatch_failure` mark the
    # RIGHT row without a second lookup. At A2 it becomes a Connection handle and nothing
    # outside this package notices; never read it from a route.
    """

    kind: TargetKind
    auth_type: AuthType
    credential_name: str | None
    context_stamp: str
    reauth_url: str | None
    _backing: Any = field(default=None, repr=False, compare=False)
    # WHY (OME-1497, G0 §5.3): the pair a non-migrated resolve read, so the request's error marks
    # can check it was not moved during the provider call. Private like `_backing`.
    _observed_pair: PairAuthority | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Authorization:
    """What `authorize` answers: the provider headers that seal one request.

    # INVARIANT: `headers` carries the Bearer token itself, so it is excluded from `repr` —
    # a logged or traced `Authorization` must never print a credential. Equality keeps it.
    """

    headers: dict[str, str] = field(repr=False)
    credential_name: str | None
    auth_type: AuthType


AvailabilityStatus = Literal["not_connected", "pending", "connected", "needs_reauth", "error"]


@dataclass(frozen=True)
class AvailabilityRow:
    """One row of the caller-scoped availability listing (D17): provider and status ONLY.

    Declared at A1 so the port's vocabulary is complete; implemented at A3 and published as
    `GET /v1/provider-access` at A4. No ids, labels, defaults or account labels — ever.
    """

    provider: str
    status: AvailabilityStatus


# --- refusals -----------------------------------------------------------------------------------


class ProviderAccessRefusal(Exception):
    """Base of every typed refusal the read interface can raise."""


class TargetMissing(ProviderAccessRefusal):
    """No stored target answers this selector, and the policy does not admit the absence."""

    def __init__(self, provider: str, requested: str) -> None:
        super().__init__(f"no credential target {requested!r} for {provider}")
        self.provider = provider
        self.requested = requested


class TargetPending(ProviderAccessRefusal):
    """The target exists but its credential flow has not completed."""

    def __init__(self, provider: str, requested: str) -> None:
        super().__init__(f"credential target {requested!r} for {provider} is still pending")
        self.provider = provider
        self.requested = requested


class TargetReauthRequired(ProviderAccessRefusal):
    """The target exists but its credential is unusable; `reauth_url` is where to fix it.

    Two shapes, both today's: raised at RESOLVE time (`message is None`) it names the target
    (provider + requested); raised at AUTHORIZE time it carries the provider's own message.
    """

    def __init__(
        self,
        provider: str,
        reauth_url: str,
        *,
        requested: str | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(message or f"re-authentication required for {provider}")
        self.provider = provider
        self.reauth_url = reauth_url
        self.requested = requested
        self.message = message


class SelectorAmbiguous(ProviderAccessRefusal):
    """The default selector matches more than one active stored target."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"multiple active connections for {provider}")
        self.provider = provider


class SelectorUnknown(ProviderAccessRefusal):
    """A named selector matches no stored target; `valid_labels` are the ones that exist."""

    def __init__(self, provider: str, requested: str, valid_labels: tuple[str, ...]) -> None:
        super().__init__(f"no connection labelled {requested!r} for {provider}")
        self.provider = provider
        self.requested = requested
        self.valid_labels = tuple(valid_labels)


class UnsupportedAuthMode(ProviderAccessRefusal):
    """The target's auth mode is one the provider does not declare."""

    def __init__(self, auth_mode: str, *, provider: str | None = None) -> None:
        super().__init__(f"auth mode {auth_mode!r} is not supported")
        self.auth_mode = auth_mode
        self.provider = provider


WriteConflictKind = Literal["retry_exhausted", "superseded"]
WriteSubject = Literal["profile", "connection"]


class WriteConflict(ProviderAccessRefusal):
    """A compare-and-set on a stored row lost: retries ran out, or the row was superseded."""

    def __init__(
        self,
        kind: WriteConflictKind,
        *,
        subject: WriteSubject,
        provider: str | None = None,
        requested: str | None = None,
    ) -> None:
        super().__init__(f"{subject} write conflict: {kind}")
        self.kind = kind
        self.subject = subject
        self.provider = provider
        self.requested = requested


class SelectorUnsupported(ProviderAccessRefusal):
    """A present `X-Profile` under the REJECT_EXPLICIT policy (Stage D sunset)."""

    def __init__(self) -> None:
        # INVARIANT: the obsolete selector value never survives the boundary in an exception that
        # a future logger could render through ``__cause__``.
        super().__init__("X-Profile is no longer supported")


class ProviderUnknown(ProviderAccessRefusal):
    """No registered provider carries this id (admin ops 8–9; A3)."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"unknown provider {provider!r}")
        self.provider = provider


class CredentialStoreUnavailable(ProviderAccessRefusal):
    """A credential-blob operation failed without exposing the adapter exception.

    # INVARIANT: the message names only the static operation and object description, never the
    # credential — store adapters may echo secrets in their own exception text, so the cause is
    # chained but never repeated here.
    """

    def __init__(self, description: str, *, operation: str = "store") -> None:
        super().__init__(f"could not {operation} {description}")
        self.description = description
        self.operation = operation


class CredentialStoreReadUnavailable(ProviderAccessRefusal):
    """The account's credential metadata could not be read (D18 §5 row 1; the successor only).

    # INVARIANT: a whole-account refusal — never a partial or an empty inventory; the adapter
    # exception is chained, never repeated.
    """

    def __init__(self) -> None:
        super().__init__("credential metadata could not be read")


class CredentialAuthorityUnavailable(ProviderAccessRefusal):
    """A pair's stored authority is unknown or inconsistent (D18 §5 row 2; the successor only).

    # INVARIANT: nothing is guessed — an unknown state, a dangling reference or an out-of-scope
    # locator is never rendered as a credential or as its absence.
    """

    def __init__(self, provider: str) -> None:
        super().__init__(f"credential authority for {provider} is unavailable")
        self.provider = provider


class PairNotManageable(ProviderAccessRefusal):
    """A pair the successor cannot address (`ambiguous`) or manage (`unresolved`).

    Raised by a D18 mutation, and by resolve for a `quarantined` pair (OME-1209 E4a).
    # INVARIANT: refused before any write and before the provider key check.
    """

    def __init__(self, provider: str, kind: Literal["ambiguous", "unresolved"]) -> None:
        super().__init__(f"credential pair for {provider} is {kind}")
        self.provider = provider
        self.kind: Literal["ambiguous", "unresolved"] = kind
